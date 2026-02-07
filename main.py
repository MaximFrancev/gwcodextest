#!/usr/bin/env python3
"""
Game & Watch Emulator — Main Entry Point

Эмулятор Nintendo Game & Watch (2020, Super Mario Bros).
Эмулирует STM32H7B0VBT6 (ARM Cortex-M7) с периферией.

Использование:
    python main.py                    # Запуск с дефолтным ROM (mario)
    python main.py --rom zelda        # Запуск с другим ROM
    python main.py --trace            # Включить трассировку CPU
    python main.py --scale 3          # Масштаб окна 3x
    python main.py --info             # Показать информацию и выйти
    python main.py --help             # Справка
"""

import sys
import os
import argparse
import time

# Добавить корень проекта в path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# === Imports ===
from utils.config import Config
from utils.logger import Logger, LogLevel

from memory.bus import SystemBus
from cpu.cortex_m7 import CortexM7
from cpu.exceptions import ExceptionManager

from peripherals.rcc import RCC
from peripherals.gpio import GPIO
from peripherals.ltdc import LTDC
from peripherals.spi import SPI
from peripherals.octospi import OCTOSPI, OCTOSPIM
from peripherals.sai import SAI
from peripherals.pwr import PWR
from peripherals.flash_ctrl import FlashInterface
from peripherals.tim import Timer
from peripherals.nvic import NVIC
from peripherals.stub import PeripheralStub

from display.renderer import DisplayRenderer
from input.keyboard import KeyboardController


def parse_args():
    """Парсинг аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Game & Watch Emulator (STM32H7B0 / ARM Cortex-M7)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Controls:
  Arrow keys     D-pad (Left/Up/Down/Right)
  Z / J          A button
  X / K          B button  
  Enter / G      Game button
  T              Time button
  P / Space      Pause/Set button
  Backspace      Power button
  Escape         Quit
        """
    )
    parser.add_argument("--rom", default="mario",
                        help="ROM name (subdirectory in roms/): mario, zelda (default: mario)")
    parser.add_argument("--scale", type=int, default=2, choices=[1, 2, 3, 4],
                        help="Display scale factor (default: 2)")
    parser.add_argument("--fps", type=int, default=60,
                        help="Target FPS (default: 60)")
    parser.add_argument("--trace", action="store_true",
                        help="Enable CPU trace logging")
    parser.add_argument("--trace-bus", action="store_true",
                        help="Enable bus trace logging")
    parser.add_argument("--trace-periph", action="store_true",
                        help="Enable peripheral trace logging")
    parser.add_argument("--trace-input", action="store_true",
                        help="Enable input trace logging")
    parser.add_argument("--log-level", default="info",
                        choices=["error", "warn", "info", "debug", "trace"],
                        help="Log level (default: info)")
    parser.add_argument("--log-file", default=None,
                        help="Log to file")
    parser.add_argument("--max-cycles", type=int, default=0,
                        help="Max CPU cycles (0 = unlimited)")
    parser.add_argument("--info", action="store_true",
                        help="Show ROM info and exit")
    parser.add_argument("--list-roms", action="store_true",
                        help="List available ROMs and exit")
    parser.add_argument("--headless", action="store_true",
                        help="Run without display (for testing)")
    parser.add_argument("--break", dest="breakpoints", nargs="*", default=[],
                        help="Breakpoint addresses (hex, e.g. 0x08001234)")
    return parser.parse_args()


def setup_peripherals(bus, cpu, config, logger):
    """
    Создать и зарегистрировать все периферийные устройства.
    Возвращает dict со всеми объектами периферии.
    """
    periphs = {}
    trace = config.trace_peripherals

    # --- RCC ---
    rcc = RCC()
    rcc.trace_enabled = trace
    bus.register_peripheral(RCC.BASE, RCC.END, rcc)
    periphs['rcc'] = rcc

    # --- GPIO ---
    gpio = GPIO()
    for port in gpio.ports.values():
        port.trace_enabled = trace
        bus.register_peripheral(port.base, port.end, port)
    periphs['gpio'] = gpio

    # --- PWR ---
    pwr = PWR()
    pwr.trace_enabled = trace
    bus.register_peripheral(PWR.BASE, PWR.END, pwr)
    periphs['pwr'] = pwr

    # --- Flash Interface ---
    flash_if = FlashInterface()
    flash_if.trace_enabled = trace
    bus.register_peripheral(FlashInterface.BASE, FlashInterface.END, flash_if)
    periphs['flash_if'] = flash_if

    # --- LTDC ---
    ltdc = LTDC()
    ltdc.trace_enabled = trace
    bus.register_peripheral(LTDC.BASE, LTDC.END, ltdc)
    periphs['ltdc'] = ltdc

    # --- SPI2 ---
    spi2 = SPI("SPI2", 0x40003800)
    spi2.trace_enabled = trace
    bus.register_peripheral(spi2.base, spi2.end, spi2)
    periphs['spi2'] = spi2

    # --- SAI1 ---
    sai1 = SAI("SAI1", 0x40015800)
    sai1.trace_enabled = trace
    bus.register_peripheral(sai1.base, sai1.end, sai1)
    periphs['sai1'] = sai1

    # --- OCTOSPI1 ---
    octospi1 = OCTOSPI("OCTOSPI1", 0x52005000)
    octospi1.trace_enabled = trace
    bus.register_peripheral(octospi1.base, octospi1.end, octospi1)
    periphs['octospi1'] = octospi1

    # --- OCTOSPI IO Manager ---
    octospim = OCTOSPIM(0x52009000)
    octospim.trace_enabled = trace
    bus.register_peripheral(octospim.base, octospim.end, octospim)
    periphs['octospim'] = octospim

    # --- Timers ---
    exc_mgr = cpu.exc_manager

    tim1 = Timer("TIM1", 0x40010000, bits=16, exc_manager=exc_mgr, irq_number=25)
    tim1.trace_enabled = trace
    bus.register_peripheral(tim1.base, tim1.end, tim1)
    periphs['tim1'] = tim1

    tim2 = Timer("TIM2", 0x40000000, bits=32, exc_manager=exc_mgr, irq_number=28)
    tim2.trace_enabled = trace
    bus.register_peripheral(tim2.base, tim2.end, tim2)
    periphs['tim2'] = tim2

    tim3 = Timer("TIM3", 0x40000400, bits=16, exc_manager=exc_mgr, irq_number=29)
    tim3.trace_enabled = trace
    bus.register_peripheral(tim3.base, tim3.end, tim3)
    periphs['tim3'] = tim3

    # --- NVIC wrapper ---
    nvic = NVIC(exc_mgr)
    nvic.trace_enabled = trace
    periphs['nvic'] = nvic

    # --- Stubs ---
    stubs = [
        ("SYSCFG",  0x58000400, 0x400),
        ("EXTI",    0x58000000, 0x400),
        ("DMA1",    0x40020000, 0x400),
        ("DMA2",    0x40020400, 0x400),
        ("BDMA",    0x58025400, 0x400),
        ("DMAMUX1", 0x40020800, 0x400),
        ("DMAMUX2", 0x58025800, 0x400),
        ("I2C1",    0x40005400, 0x400),
        ("IWDG",    0x58004800, 0x400),
        ("DBGMCU",  0x5C001000, 0x400),
        ("TIM4",    0x40000800, 0x400),
        ("TIM5",    0x40000C00, 0x400),
        ("TIM6",    0x40001000, 0x400),
        ("TIM7",    0x40001400, 0x400),
        ("USART1",  0x40011000, 0x400),
        ("RNG",     0x48021800, 0x400),
        ("CRC",     0x58024C00, 0x400),
    ]

    for name, base, size in stubs:
        stub = PeripheralStub(name, base, size)
        stub.trace_enabled = trace
        bus.register_peripheral(base, base + size - 1, stub)
    periphs['stubs'] = stubs

    logger.info("INIT", f"Registered {len(periphs)} peripheral groups "
                        f"+ {len(stubs)} stubs")

    return periphs


def main():
    """Главная функция эмулятора."""
    args = parse_args()

    # === Logger ===
    log_levels = {
        "error": LogLevel.ERROR, "warn": LogLevel.WARN,
        "info": LogLevel.INFO, "debug": LogLevel.DEBUG,
        "trace": LogLevel.TRACE,
    }
    log_level = log_levels.get(args.log_level, LogLevel.INFO)
    if args.trace:
        log_level = LogLevel.TRACE

    logger = Logger(level=log_level, log_file=args.log_file)

    logger.info("INIT", "=" * 50)
    logger.info("INIT", "  Game & Watch Emulator")
    logger.info("INIT", "  STM32H7B0 / ARM Cortex-M7")
    logger.info("INIT", "=" * 50)

    # === Config ===
    config = Config(rom_name=args.rom)
    config.display_scale = args.scale
    config.target_fps = args.fps
    config.trace_cpu = args.trace
    config.trace_bus = args.trace_bus
    config.trace_peripherals = args.trace_periph
    config.trace_input = args.trace_input
    if args.max_cycles > 0:
        config.max_instructions = args.max_cycles

    for bp in args.breakpoints:
        try:
            addr = int(bp, 0)
            config.breakpoints.add(addr)
            logger.info("INIT", f"Breakpoint: 0x{addr:08X}")
        except ValueError:
            logger.warn("INIT", f"Invalid breakpoint: {bp}")

    # === List ROMs ===
    if args.list_roms:
        roms = config.list_available_roms()
        print("\nAvailable ROMs:")
        for rom in roms:
            status = "✓" if rom['has_flash'] else "✗ (no internal_flash.bin)"
            print(f"  {rom['name']:12s} {status}")
        if not roms:
            print("  (none found in roms/ directory)")
        return 0

    # === ROM Info ===
    print(config.get_rom_info())

    if args.info:
        return 0

    # === Validate ROM ===
    ok, errors = config.validate()
    if not ok:
        for err in errors:
            logger.error("INIT", err)
        logger.error("INIT", "ROM validation failed. Cannot start.")
        return 1

    # === Create system ===
    logger.info("INIT", "Creating system...")

    bus = SystemBus()
    bus.trace_enabled = config.trace_bus

    cpu = CortexM7(bus)
    cpu.trace_enabled = config.trace_cpu
    bus.set_exc_manager(cpu.exc_manager)

    periphs = setup_peripherals(bus, cpu, config, logger)

    # === Load ROM ===
    logger.info("INIT", "Loading ROM files...")

    loaded = bus.load_rom(
        internal_flash_path=config.internal_flash_path,
        external_flash_path=config.external_flash_path,
        itcm_path=config.itcm_path,
        key_info_path=config.key_info_path,
    )

    logger.info("INIT", f"Loaded: {loaded}")

    # Verify vector table is correct (read from Flash alias)
    sp_check = bus.read32(0x00000000)
    pc_check = bus.read32(0x00000004)
    logger.info("INIT", f"Vector table check (via 0x00000000):")
    logger.info("INIT", f"  Initial SP:     0x{sp_check:08X}")
    logger.info("INIT", f"  Reset vector:   0x{pc_check:08X}")

    # Also show from Flash directly
    sp_flash = bus.read32(0x08000000)
    pc_flash = bus.read32(0x08000004)
    logger.info("INIT", f"Vector table (via 0x08000000):")
    logger.info("INIT", f"  Initial SP:     0x{sp_flash:08X}")
    logger.info("INIT", f"  Reset vector:   0x{pc_flash:08X}")

    # Sanity check
    if sp_check != sp_flash or pc_check != pc_flash:
        logger.error("INIT", "Vector table mismatch! Boot alias not working correctly.")
        logger.error("INIT", f"  Alias: SP=0x{sp_check:08X} PC=0x{pc_check:08X}")
        logger.error("INIT", f"  Flash: SP=0x{sp_flash:08X} PC=0x{pc_flash:08X}")

    # Validate vector table values
    if not (0x20000000 <= sp_check <= 0x20020000):
        logger.warn("INIT", f"SP 0x{sp_check:08X} doesn't look like DTCM address")
    if not (0x08000000 <= (pc_check & 0xFFFFFFFE) <= 0x08200000):
        logger.warn("INIT", f"Reset vector 0x{pc_check:08X} doesn't look like Flash address")

    # === Display ===
    display = None
    if not args.headless:
        display = DisplayRenderer(
            scale=config.display_scale,
            title=f"Game & Watch - {config.rom_name.upper()}"
        )
        if not display.init(bus=bus):
            logger.warn("INIT", "Display init failed, running headless")
            display = None

    # === Input ===
    kb = KeyboardController(gpio=periphs['gpio'])
    kb.trace_enabled = config.trace_input
    if display and display.is_active:
        kb.init()
        logger.info("INIT", "Keyboard input initialized")

    # === Reset CPU ===
    # IMPORTANT: boot_from_flash must be True here so CPU reads
    # correct vector table from Flash Bank1 alias
    bus.set_boot_from_flash(True)
    logger.info("INIT", "Resetting CPU (boot from Flash)...")
    cpu.reset()
    logger.info("INIT", f"CPU after reset: PC=0x{cpu.regs.pc:08X} SP=0x{cpu.regs.sp:08X}")

    # Now apply ITCM override (firmware will use this for fast code)
    # The vector table is already read, so this is safe
    bus.apply_itcm_override()

    # === Main Loop ===
    logger.info("RUN", "Entering main loop...")
    logger.info("RUN", f"Target: {config.target_fps} FPS, "
                       f"{config.cpu_cycles_per_frame} cycles/frame")

    running = True
    frame_count = 0
    total_cycles = 0
    start_time = time.time()
    frame_interval = 1.0 / config.target_fps
    ltdc = periphs['ltdc']
    cpf = config.cpu_cycles_per_frame

    # Error tracking
    consecutive_errors = 0
    max_consecutive_errors = 100

    try:
        while running:
            frame_start = time.time()

            # --- Process events ---
            if display and display.is_active:
                for event in _get_pygame_events():
                    if event.type == _PYGAME_QUIT:
                        running = False
                    elif event.type == _PYGAME_KEYDOWN:
                        if event.key == _PYGAME_K_ESCAPE:
                            running = False

                kb.update()

            # --- Execute CPU cycles for one frame ---
            cycles_this_frame = 0
            frame_errors = 0

            while cycles_this_frame < cpf:
                # Check breakpoints
                if config.breakpoints and cpu.regs.pc in config.breakpoints:
                    logger.warn("CPU", f"BREAKPOINT at 0x{cpu.regs.pc:08X}")
                    logger.info("CPU", cpu.regs.dump())
                    running = False
                    break

                # Step CPU
                try:
                    cycles = cpu.step()
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    frame_errors += 1

                    if consecutive_errors <= 5:
                        logger.error("CPU",
                                     f"Exception at PC=0x{cpu.regs.pc:08X}: {e}")

                    if consecutive_errors >= max_consecutive_errors:
                        logger.error("CPU",
                                     f"Too many consecutive errors "
                                     f"({consecutive_errors}), stopping")
                        logger.error("CPU", cpu.regs.dump())
                        running = False
                        break

                    # Try to skip the problematic instruction
                    cpu.regs.pc = (cpu.regs.pc + 2) & 0xFFFFFFFE
                    cycles = 1

                cycles_this_frame += cycles
                total_cycles += cycles

                # Tick SysTick
                bus.tick_systick()

                # Tick timers periodically
                if (cycles_this_frame & 0x3F) == 0:
                    for tname in ('tim1', 'tim2', 'tim3'):
                        periphs[tname].tick(64)

                # Tick LTDC to generate VSYNC/line flags
                ltdc.tick(cycles, cycles_per_vsync=cpf)

                # Max cycles check
                if 0 < config.max_instructions <= total_cycles:
                    logger.info("RUN", f"Max cycles reached: {total_cycles}")
                    running = False
                    break

            # --- Render frame ---
            if display and display.is_active:
                if ltdc.enabled:
                    display.configure_from_ltdc(ltdc)

                if display._fb_address != 0:
                    display.render_frame_fast()
                else:
                    display.render_frame()

                display.limit_fps(config.target_fps)

            frame_count += 1

            # --- Status update ---
            if frame_count % 60 == 0:
                elapsed = time.time() - start_time
                if elapsed > 0:
                    avg_fps = frame_count / elapsed
                    mhz = total_cycles / elapsed / 1_000_000
                    logger.info("RUN",
                                f"Frame {frame_count}, "
                                f"{avg_fps:.1f} FPS, "
                                f"{mhz:.1f} MHz emulated, "
                                f"PC=0x{cpu.regs.pc:08X}")

    except KeyboardInterrupt:
        logger.info("RUN", "Interrupted by user (Ctrl+C)")

    # === Shutdown ===
    elapsed = time.time() - start_time
    logger.info("EXIT", "=" * 50)
    logger.info("EXIT", f"Total frames:     {frame_count}")
    logger.info("EXIT", f"Total cycles:     {total_cycles:,}")
    logger.info("EXIT", f"Elapsed time:     {elapsed:.2f}s")
    if elapsed > 0:
        logger.info("EXIT", f"Average FPS:      {frame_count / elapsed:.1f}")
        logger.info("EXIT", f"Emulated speed:   {total_cycles / elapsed / 1e6:.1f} MHz")
    logger.info("EXIT", f"Final PC:         0x{cpu.regs.pc:08X}")
    logger.info("EXIT", f"Final SP:         0x{cpu.regs.sp:08X}")
    logger.info("EXIT", cpu.regs.dump())
    logger.info("EXIT", "=" * 50)

    if display:
        display.shutdown()

    logger.close()
    return 0


# === Pygame helpers ===
_PYGAME_QUIT = None
_PYGAME_KEYDOWN = None
_PYGAME_K_ESCAPE = None


def _get_pygame_events():
    global _PYGAME_QUIT, _PYGAME_KEYDOWN, _PYGAME_K_ESCAPE
    try:
        import pygame
        if _PYGAME_QUIT is None:
            _PYGAME_QUIT = pygame.QUIT
            _PYGAME_KEYDOWN = pygame.KEYDOWN
            _PYGAME_K_ESCAPE = pygame.K_ESCAPE
        return pygame.event.get()
    except ImportError:
        return []


if __name__ == "__main__":
    sys.exit(main() or 0)

"""
Configuration — пути к ROM, настройки эмулятора.

Автоматически определяет пути относительно корня проекта.
Поддерживает разные ROM-наборы (mario, zelda).
"""

import os
import json


class Config:
    """
    Конфигурация эмулятора Game & Watch.
    
    Структура директорий:
        project_root/
        ├── main.py
        ├── cpu/
        ├── memory/
        ├── peripherals/
        ├── display/
        ├── input/
        ├── audio/
        ├── crypto/
        ├── utils/
        ├── roms/
        │   ├── mario/
        │   │   ├── internal_flash.bin
        │   │   ├── external_flash.bin
        │   │   ├── external_flash_decrypted.bin
        │   │   ├── itcm.bin
        │   │   └── (Key Info).json
        │   └── zelda/
        │       └── ...
        └── docs/
    """

    def __init__(self, rom_name="mario"):
        """
        rom_name: имя поддиректории в roms/ ("mario", "zelda")
        """
        # Корень проекта — директория где лежит main.py
        # Определяем относительно расположения этого файла (utils/config.py)
        self._utils_dir = os.path.dirname(os.path.abspath(__file__))
        self._project_root = os.path.dirname(self._utils_dir)

        self.rom_name = rom_name

        # === Пути ===
        self.roms_dir = os.path.join(self._project_root, "roms")
        self.rom_dir = os.path.join(self.roms_dir, rom_name)
        self.docs_dir = os.path.join(self._project_root, "docs")

        # ROM файлы
        self.internal_flash_path = os.path.join(self.rom_dir, "internal_flash.bin")
        self.external_flash_path = self._find_external_flash()
        self.itcm_path = os.path.join(self.rom_dir, "itcm.bin")
        self.key_info_path = os.path.join(self.rom_dir, "(Key Info).json")

        # === Настройки эмулятора ===
        self.display_scale = 2          # Масштаб окна (1x, 2x, 3x)
        self.target_fps = 60            # Целевой FPS
        self.cpu_cycles_per_frame = 4_666_667  # ~280MHz / 60fps
        self.audio_enabled = False      # Звук (пока отключён)
        self.trace_cpu = False          # Трассировка CPU
        self.trace_bus = False          # Трассировка шины
        self.trace_peripherals = False  # Трассировка периферии
        self.trace_input = False        # Трассировка ввода
        self.max_instructions = 0       # Лимит инструкций (0 = без лимита)
        self.breakpoints = set()        # Адреса останова

        # === Тайминги ===
        self.cpu_freq_hz = 280_000_000  # 280 MHz (STM32H7B0 max)
        self.systick_freq_hz = 1000     # SysTick обычно 1kHz

    def _find_external_flash(self):
        """
        Найти файл external flash.
        Приоритет: decrypted > encrypted.
        """
        decrypted = os.path.join(self.rom_dir, "external_flash_decrypted.bin")
        encrypted = os.path.join(self.rom_dir, "external_flash.bin")

        if os.path.exists(decrypted):
            return decrypted
        if os.path.exists(encrypted):
            return encrypted
        return decrypted  # default path даже если не существует

    def validate(self):
        """
        Проверить наличие необходимых файлов.
        
        Возвращает (ok: bool, errors: list[str]).
        """
        errors = []

        if not os.path.isdir(self.rom_dir):
            errors.append(f"ROM directory not found: {self.rom_dir}")
            return False, errors

        if not os.path.exists(self.internal_flash_path):
            errors.append(f"Internal flash not found: {self.internal_flash_path}")

        if not os.path.exists(self.external_flash_path):
            # Попробовать оба варианта
            alt = os.path.join(self.rom_dir, "external_flash.bin")
            if not os.path.exists(alt):
                errors.append(
                    f"External flash not found: neither "
                    f"external_flash_decrypted.bin nor external_flash.bin"
                )

        if not os.path.exists(self.itcm_path):
            # ITCM опционален — Flash Bank1 будет использован как fallback
            pass  # не ошибка

        if not os.path.exists(self.key_info_path):
            # Ключи нужны только для зашифрованного дампа
            if self.external_flash_path and 'decrypted' not in self.external_flash_path:
                errors.append(f"Key info not found (needed for encrypted flash): "
                              f"{self.key_info_path}")

        ok = len(errors) == 0
        return ok, errors

    def get_rom_info(self):
        """Информация о ROM для отладки."""
        lines = [f"=== ROM: {self.rom_name} ==="]
        lines.append(f"  ROM dir:        {self.rom_dir}")

        files = [
            ("Internal Flash", self.internal_flash_path),
            ("External Flash", self.external_flash_path),
            ("ITCM",           self.itcm_path),
            ("Key Info",       self.key_info_path),
        ]

        for name, path in files:
            exists = os.path.exists(path)
            if exists:
                size = os.path.getsize(path)
                if size >= 1024:
                    size_str = f"{size // 1024}KB"
                else:
                    size_str = f"{size}B"
                lines.append(f"  {name:18s}: {size_str:>8s}  ✓")
            else:
                lines.append(f"  {name:18s}:          ✗  (not found)")

        return '\n'.join(lines)

    def list_available_roms(self):
        """Список доступных ROM-наборов."""
        if not os.path.isdir(self.roms_dir):
            return []
        roms = []
        for entry in os.listdir(self.roms_dir):
            rom_path = os.path.join(self.roms_dir, entry)
            if os.path.isdir(rom_path):
                # Проверить наличие хотя бы internal_flash.bin
                has_flash = os.path.exists(
                    os.path.join(rom_path, "internal_flash.bin")
                )
                roms.append({
                    'name': entry,
                    'path': rom_path,
                    'has_flash': has_flash,
                })
        return roms

    def __repr__(self):
        return (f"Config(rom={self.rom_name}, "
                f"scale={self.display_scale}, "
                f"fps={self.target_fps})")

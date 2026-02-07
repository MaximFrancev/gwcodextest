"""
SRAM Emulation

Эмулирует все регионы оперативной памяти STM32H7B0:
- ITCM RAM (64KB)
- DTCM RAM (128KB)
- AXI SRAM (1MB)
- AHB SRAM1 (128KB)
- AHB SRAM2 (32KB)
- Backup SRAM (4KB)

Общий объём: ~1380KB (как в спецификации Game & Watch)
"""

import struct


class RAMRegion:
    """Один регион оперативной памяти."""

    def __init__(self, name, base_address, size, init_value=0x00):
        """
        name: имя региона для отладки
        base_address: начальный адрес в адресном пространстве
        size: размер в байтах
        init_value: значение для инициализации (0x00 или 0xFF)
        """
        self.name = name
        self.base = base_address
        self.size = size
        self.end = base_address + size - 1
        self._data = bytearray([init_value] * size)

    def contains(self, address):
        """Проверить, попадает ли адрес в этот регион."""
        return self.base <= address <= self.end

    def _offset(self, address):
        """Вычислить смещение внутри региона."""
        off = address - self.base
        if off < 0 or off >= self.size:
            raise MemoryError(
                f"[{self.name}] Address 0x{address:08X} out of range "
                f"(0x{self.base:08X}-0x{self.end:08X})"
            )
        return off

    # === Чтение ===

    def read8(self, address):
        off = self._offset(address)
        return self._data[off]

    def read16(self, address):
        off = self._offset(address)
        return struct.unpack_from('<H', self._data, off)[0]

    def read32(self, address):
        off = self._offset(address)
        return struct.unpack_from('<I', self._data, off)[0]

    # === Запись ===

    def write8(self, address, value):
        off = self._offset(address)
        self._data[off] = value & 0xFF

    def write16(self, address, value):
        off = self._offset(address)
        struct.pack_into('<H', self._data, off, value & 0xFFFF)

    def write32(self, address, value):
        off = self._offset(address)
        struct.pack_into('<I', self._data, off, value & 0xFFFFFFFF)

    # === Блочные операции ===

    def read_block(self, address, size):
        """Прочитать блок байтов."""
        off = self._offset(address)
        if off + size > self.size:
            raise MemoryError(
                f"[{self.name}] Block read 0x{address:08X}+{size} exceeds region"
            )
        return bytes(self._data[off:off + size])

    def write_block(self, address, data):
        """Записать блок байтов."""
        off = self._offset(address)
        size = len(data)
        if off + size > self.size:
            raise MemoryError(
                f"[{self.name}] Block write 0x{address:08X}+{size} exceeds region"
            )
        self._data[off:off + size] = data

    def load_from_bytes(self, data, offset=0):
        """
        Загрузить данные в регион.
        data: bytes/bytearray
        offset: смещение внутри региона
        """
        size = len(data)
        if offset + size > self.size:
            # Обрезаем если данные больше региона
            size = self.size - offset
            data = data[:size]
        self._data[offset:offset + size] = data

    def clear(self, value=0x00):
        """Очистить весь регион."""
        self._data = bytearray([value] * self.size)

    def __repr__(self):
        return f"RAM({self.name}: 0x{self.base:08X}, {self.size // 1024}KB)"


class SRAMController:
    """
    Контроллер всех регионов SRAM.
    
    Маршрутизирует обращения к нужному региону по адресу.
    """

    def __init__(self):
        # Создаём все регионы RAM
        self.itcm = RAMRegion("ITCM_RAM", 0x00000000, 64 * 1024)
        self.dtcm = RAMRegion("DTCM_RAM", 0x20000000, 128 * 1024)
        self.axi_sram = RAMRegion("AXI_SRAM", 0x24000000, 1024 * 1024)
        self.ahb_sram1 = RAMRegion("AHB_SRAM1", 0x30000000, 128 * 1024)
        self.ahb_sram2 = RAMRegion("AHB_SRAM2", 0x30020000, 32 * 1024)
        self.backup_sram = RAMRegion("BACKUP_SRAM", 0x38800000, 4 * 1024)

        # Список для быстрого поиска (в порядке вероятности обращения)
        self._regions = [
            self.dtcm,
            self.axi_sram,
            self.itcm,
            self.ahb_sram1,
            self.ahb_sram2,
            self.backup_sram,
        ]

        # Кеш маршрутизации: верхние биты адреса → регион
        self._route_cache = {}

    def _find_region(self, address):
        """Найти регион по адресу."""
        # Быстрая проверка по верхнему байту
        top = address >> 24
        cached = self._route_cache.get(top)
        if cached is not None and cached.contains(address):
            return cached

        for region in self._regions:
            if region.contains(address):
                self._route_cache[top] = region
                return region

        return None

    def contains(self, address):
        """Проверить, есть ли RAM по этому адресу."""
        return self._find_region(address) is not None

    # === Чтение ===

    def read8(self, address):
        region = self._find_region(address)
        if region:
            return region.read8(address)
        return 0

    def read16(self, address):
        region = self._find_region(address)
        if region:
            return region.read16(address)
        return 0

    def read32(self, address):
        region = self._find_region(address)
        if region:
            return region.read32(address)
        return 0

    # === Запись ===

    def write8(self, address, value):
        region = self._find_region(address)
        if region:
            region.write8(address, value)

    def write16(self, address, value):
        region = self._find_region(address)
        if region:
            region.write16(address, value)

    def write32(self, address, value):
        region = self._find_region(address)
        if region:
            region.write32(address, value)

    def load_itcm(self, data):
        """Загрузить данные в ITCM RAM (из itcm.bin)."""
        self.itcm.load_from_bytes(data)

    def reset(self):
        """Сброс всей SRAM (опционально)."""
        # В реальном MCU SRAM не очищается при сбросе,
        # но для чистоты эмуляции можно
        pass

    def dump_region(self, address, size=64):
        """Дамп памяти для отладки."""
        region = self._find_region(address)
        if not region:
            return f"No RAM at 0x{address:08X}"

        lines = [f"--- {region.name} @ 0x{address:08X} ---"]
        data = region.read_block(address, min(size, region.end - address + 1))

        for i in range(0, len(data), 16):
            hex_str = ' '.join(f'{b:02X}' for b in data[i:i + 16])
            ascii_str = ''.join(
                chr(b) if 32 <= b < 127 else '.' for b in data[i:i + 16]
            )
            lines.append(f"  0x{address + i:08X}: {hex_str:<48s} {ascii_str}")

        return '\n'.join(lines)

    def __repr__(self):
        total = sum(r.size for r in self._regions)
        return f"SRAMController({total // 1024}KB total, {len(self._regions)} regions)"
"""
Flash Memory Emulation

Эмулирует внутреннюю Flash память STM32H7B0:
- Bank 1: 128KB at 0x08000000
- Bank 2: 128KB at 0x08100000 (undocumented, found by modding community)

Flash память read-only во время исполнения (запись через Flash interface).
При сбросе ITCM (0x00000000) является зеркалом Bank 1 (по умолчанию).
"""

import struct
import os


class FlashBank:
    """Один банк внутренней Flash."""

    def __init__(self, name, base_address, size):
        self.name = name
        self.base = base_address
        self.size = size
        self.end = base_address + size - 1
        self._data = bytearray([0xFF] * size)  # Flash стирается в 0xFF

    def contains(self, address):
        return self.base <= address <= self.end

    def _offset(self, address):
        off = address - self.base
        if off < 0 or off >= self.size:
            raise MemoryError(
                f"[{self.name}] Address 0x{address:08X} out of range "
                f"(0x{self.base:08X}-0x{self.end:08X})"
            )
        return off

    def read8(self, address):
        return self._data[self._offset(address)]

    def read16(self, address):
        off = self._offset(address)
        return struct.unpack_from('<H', self._data, off)[0]

    def read32(self, address):
        off = self._offset(address)
        return struct.unpack_from('<I', self._data, off)[0]

    def read_block(self, address, size):
        off = self._offset(address)
        end = min(off + size, self.size)
        return bytes(self._data[off:end])

    def load_from_bytes(self, data, offset=0):
        """Загрузить бинарные данные в Flash банк."""
        size = len(data)
        if offset + size > self.size:
            size = self.size - offset
            data = data[:size]
        self._data[offset:offset + size] = data

    def load_from_file(self, filepath, offset=0):
        """Загрузить Flash банк из файла."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Flash image not found: {filepath}")

        with open(filepath, 'rb') as f:
            data = f.read()

        self.load_from_bytes(data, offset)
        return len(data)

    @property
    def data(self):
        return bytes(self._data)

    def __repr__(self):
        return f"FlashBank({self.name}: 0x{self.base:08X}, {self.size // 1024}KB)"


class FlashController:
    """
    Контроллер внутренней Flash памяти.
    
    Управляет двумя банками Flash и зеркалированием в ITCM.
    
    Адресное пространство:
    - 0x08000000-0x0801FFFF: Bank 1 (128KB)
    - 0x08100000-0x0811FFFF: Bank 2 (128KB)
    
    При загрузке, Bank 1 копируется в ITCM (0x00000000),
    чтобы vector table и boot code были доступны по адресу 0.
    """

    def __init__(self):
        self.bank1 = FlashBank("FLASH_B1", 0x08000000, 128 * 1024)
        self.bank2 = FlashBank("FLASH_B2", 0x08100000, 128 * 1024)

        self._banks = [self.bank1, self.bank2]

    def contains(self, address):
        """Проверить, попадает ли адрес во Flash."""
        for bank in self._banks:
            if bank.contains(address):
                return True
        return False

    def _find_bank(self, address):
        """Найти банк по адресу."""
        for bank in self._banks:
            if bank.contains(address):
                return bank
        return None

    # === Чтение (Flash доступна только на чтение) ===

    def read8(self, address):
        bank = self._find_bank(address)
        if bank:
            return bank.read8(address)
        return 0xFF

    def read16(self, address):
        bank = self._find_bank(address)
        if bank:
            return bank.read16(address)
        return 0xFFFF

    def read32(self, address):
        bank = self._find_bank(address)
        if bank:
            return bank.read32(address)
        return 0xFFFFFFFF

    # === Запись (не поддерживается напрямую) ===

    def write8(self, address, value):
        # Flash запись игнорируется (нужен Flash interface для программирования)
        pass

    def write16(self, address, value):
        pass

    def write32(self, address, value):
        pass

    # === Загрузка ROM ===

    def load_internal_flash(self, filepath):
        """
        Загрузить internal_flash.bin.
        
        Файл содержит дамп всей внутренней Flash.
        Размер может быть 128KB (только Bank1) или 256KB (оба банка).
        
        Возвращает размер загруженных данных.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Internal flash image not found: {filepath}")

        with open(filepath, 'rb') as f:
            data = f.read()

        total_loaded = 0

        # Bank 1: первые 128KB
        bank1_size = min(len(data), 128 * 1024)
        self.bank1.load_from_bytes(data[:bank1_size])
        total_loaded += bank1_size

        # Bank 2: следующие 128KB (если есть)
        if len(data) > 128 * 1024:
            bank2_data = data[128 * 1024:]
            bank2_size = min(len(bank2_data), 128 * 1024)
            self.bank2.load_from_bytes(bank2_data[:bank2_size])
            total_loaded += bank2_size

        return total_loaded

    def get_vector_table(self):
        """
        Прочитать vector table из Bank 1.
        
        Возвращает dict с основными векторами:
        - initial_sp: начальное значение MSP
        - reset: адрес Reset Handler
        - nmi: адрес NMI Handler
        - hardfault: адрес HardFault Handler
        - и т.д.
        """
        vectors = {}
        vector_names = [
            'initial_sp',    # 0x00
            'reset',         # 0x04
            'nmi',           # 0x08
            'hardfault',     # 0x0C
            'memmanage',     # 0x10
            'busfault',      # 0x14
            'usagefault',    # 0x18
            'reserved_1c',   # 0x1C
            'reserved_20',   # 0x20
            'reserved_24',   # 0x24
            'reserved_28',   # 0x28
            'svcall',        # 0x2C
            'debugmon',      # 0x30
            'reserved_34',   # 0x34
            'pendsv',        # 0x38
            'systick',       # 0x3C
        ]

        for i, name in enumerate(vector_names):
            addr = i * 4
            val = self.bank1.read32(self.bank1.base + addr)
            vectors[name] = val

        return vectors

    def get_boot_data_for_itcm(self):
        """
        Получить данные Bank 1 для копирования в ITCM.
        
        На реальном STM32H7B0, при загрузке по умолчанию 
        адрес 0x00000000 зеркалирует Flash Bank 1 (0x08000000).
        
        Возвращает bytes для загрузки в ITCM.
        """
        return self.bank1.data

    def dump_vectors(self):
        """Дамп vector table для отладки."""
        vectors = self.get_vector_table()
        lines = ["=== Vector Table ==="]
        for name, val in vectors.items():
            lines.append(f"  {name:16s}: 0x{val:08X}")
        return '\n'.join(lines)

    def __repr__(self):
        total = sum(b.size for b in self._banks)
        return f"FlashController({total // 1024}KB, {len(self._banks)} banks)"
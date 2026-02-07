"""
Generic Peripheral Stub

Заглушка для любого периферийного устройства.
Хранит записанные значения и возвращает их при чтении.
Позволяет задать значения по умолчанию для конкретных регистров.
"""


class PeripheralStub:
    """
    Универсальная заглушка периферии.
    
    Использование:
        stub = PeripheralStub("MY_PERIPH", 0x40001000, 0x400)
        bus.register_peripheral(0x40001000, 0x400013FF, stub)
    """

    def __init__(self, name, base_address, size, defaults=None):
        """
        name: имя для логирования
        base_address: базовый адрес
        size: размер адресного пространства
        defaults: dict {offset: default_value} — значения по умолчанию
        """
        self.name = name
        self.base = base_address
        self.size = size
        self.end = base_address + size - 1
        
        # Хранилище регистров (offset -> value)
        self._regs = {}
        
        # Значения по умолчанию
        if defaults:
            for offset, val in defaults.items():
                self._regs[offset] = val
        
        # Trace
        self.trace_enabled = False
        self._logged_reads = set()
        self._logged_writes = set()

    def _offset(self, address):
        return address - self.base

    def contains(self, address):
        return self.base <= address <= self.end

    # === Read ===

    def read8(self, address):
        off = self._offset(address)
        val32 = self._regs.get(off & ~3, 0)
        byte_pos = off & 3
        return (val32 >> (byte_pos * 8)) & 0xFF

    def read16(self, address):
        off = self._offset(address)
        val32 = self._regs.get(off & ~3, 0)
        if off & 2:
            return (val32 >> 16) & 0xFFFF
        return val32 & 0xFFFF

    def read32(self, address):
        off = self._offset(address)
        val = self._regs.get(off, 0)
        if self.trace_enabled and off not in self._logged_reads:
            self._logged_reads.add(off)
            print(f"[{self.name}] Read  +0x{off:03X} -> 0x{val:08X}")
        return val

    # === Write ===

    def write8(self, address, value):
        off = self._offset(address)
        aligned = off & ~3
        old = self._regs.get(aligned, 0)
        byte_pos = off & 3
        mask = 0xFF << (byte_pos * 8)
        new = (old & ~mask) | ((value & 0xFF) << (byte_pos * 8))
        self._regs[aligned] = new

    def write16(self, address, value):
        off = self._offset(address)
        aligned = off & ~3
        old = self._regs.get(aligned, 0)
        if off & 2:
            new = (old & 0x0000FFFF) | ((value & 0xFFFF) << 16)
        else:
            new = (old & 0xFFFF0000) | (value & 0xFFFF)
        self._regs[aligned] = new

    def write32(self, address, value):
        off = self._offset(address)
        self._regs[off] = value & 0xFFFFFFFF
        if self.trace_enabled and off not in self._logged_writes:
            self._logged_writes.add(off)
            print(f"[{self.name}] Write +0x{off:03X} = 0x{value:08X}")

    def reset(self):
        """Сброс всех регистров."""
        self._regs.clear()

    def __repr__(self):
        return f"Stub({self.name}: 0x{self.base:08X}, {self.size} bytes)"

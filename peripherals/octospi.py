"""
OCTOSPI — Octo-SPI Interface (STM32H7B0)

Управляет доступом к внешней SPI Flash.
В memory-mapped режиме адреса 0x90000000+ автоматически
транслируются в чтение Flash через шину.

OCTOSPI1: 0x52005000
OCTOSPI IO Manager: 0x52009000

Для эмуляции: memory-mapped доступ обрабатывается в bus.py,
здесь только регистры конфигурации.
"""


class OCTOSPI:
    """STM32H7B0 OCTOSPI peripheral."""

    SIZE = 0x400

    # Register offsets
    CR      = 0x000   # Control
    DCR1    = 0x008   # Device Configuration 1
    DCR2    = 0x00C   # Device Configuration 2
    DCR3    = 0x010   # Device Configuration 3
    DCR4    = 0x014   # Device Configuration 4
    SR      = 0x020   # Status
    FCR     = 0x024   # Flag Clear
    DLR     = 0x040   # Data Length
    AR      = 0x048   # Address
    DR      = 0x050   # Data
    PSMKR   = 0x080   # Polling Status Mask
    PSMAR   = 0x088   # Polling Status Match
    PIR     = 0x090   # Polling Interval
    CCR     = 0x100   # Communication Configuration
    TCR     = 0x108   # Timing Configuration
    IR      = 0x110   # Instruction
    ABR     = 0x120   # Alternate Bytes
    LPTR    = 0x130   # Low-Power Timeout
    WPCCR   = 0x140   # Wrap Communication Configuration
    WPTCR   = 0x148   # Wrap Timing Configuration
    WPIR    = 0x150   # Wrap Instruction
    WPABR   = 0x160   # Wrap Alternate Bytes
    WCCR    = 0x180   # Write Communication Configuration
    WTCR    = 0x188   # Write Timing Configuration
    WIR     = 0x190   # Write Instruction
    WABR    = 0x1A0   # Write Alternate Bytes
    HLCR    = 0x200   # HyperBus Latency Configuration

    def __init__(self, name, base_address):
        self.name = name
        self.base = base_address
        self.end = base_address + self.SIZE - 1
        self._regs = {}
        self.trace_enabled = False
        self.reset()

    def reset(self):
        self._regs = {
            self.CR:   0x00000000,
            self.DCR1: 0x00000000,
            self.DCR2: 0x00000000,
            self.DCR3: 0x00000000,
            self.SR:   0x00000004,  # FTF=1 (FIFO threshold flag)
            self.CCR:  0x00000000,
        }

    def contains(self, address):
        return self.base <= address <= self.end

    def _offset(self, address):
        return address - self.base

    def read32(self, address):
        off = self._offset(address)

        if off == self.SR:
            return self._read_sr()

        if off == self.DR:
            return 0  # Нет данных в indirect mode

        val = self._regs.get(off, 0)
        if self.trace_enabled:
            print(f"[{self.name}] Read +0x{off:03X} -> 0x{val:08X}")
        return val

    def write32(self, address, value):
        off = self._offset(address)
        value &= 0xFFFFFFFF

        if self.trace_enabled:
            print(f"[{self.name}] Write +0x{off:03X} = 0x{value:08X}")

        if off == self.FCR:
            sr = self._regs.get(self.SR, 0)
            self._regs[self.SR] = sr & ~value
            return

        self._regs[off] = value

    def read8(self, address):
        val32 = self.read32(address & ~3)
        return (val32 >> ((address & 3) * 8)) & 0xFF

    def read16(self, address):
        val32 = self.read32(address & ~3)
        if address & 2:
            return (val32 >> 16) & 0xFFFF
        return val32 & 0xFFFF

    def write8(self, address, value):
        aligned = address & ~3
        off = self._offset(aligned)
        old = self._regs.get(off, 0)
        bp = address & 3
        mask = 0xFF << (bp * 8)
        self.write32(aligned, (old & ~mask) | ((value & 0xFF) << (bp * 8)))

    def write16(self, address, value):
        aligned = address & ~3
        off = self._offset(aligned)
        old = self._regs.get(off, 0)
        if address & 2:
            new = (old & 0x0000FFFF) | ((value & 0xFFFF) << 16)
        else:
            new = (old & 0xFFFF0000) | (value & 0xFFFF)
        self.write32(aligned, new)

    def _read_sr(self):
        """
        Status Register:
        Bit 1: FTF — FIFO threshold flag (ready)
        Bit 2: TCF — Transfer complete flag
        Bit 5: BUSY
        """
        sr = self._regs.get(self.SR, 0)
        sr |= (1 << 1)   # FTF: FIFO ready
        sr |= (1 << 2)   # TCF: transfer complete
        sr &= ~(1 << 5)  # Not busy
        return sr

    def __repr__(self):
        cr = self._regs.get(self.CR, 0)
        return f"{self.name}(CR=0x{cr:08X})"


class OCTOSPIM:
    """OCTOSPI IO Manager — маршрутизация пинов OCTOSPI."""

    SIZE = 0x400

    def __init__(self, base_address=0x52009000):
        self.name = "OCTOSPIM"
        self.base = base_address
        self.end = base_address + self.SIZE - 1
        self._regs = {}
        self.trace_enabled = False

    def contains(self, address):
        return self.base <= address <= self.end

    def _offset(self, address):
        return address - self.base

    def read32(self, address):
        off = self._offset(address)
        return self._regs.get(off, 0)

    def write32(self, address, value):
        off = self._offset(address)
        self._regs[off] = value & 0xFFFFFFFF

    def read8(self, address):
        return (self.read32(address & ~3) >> ((address & 3) * 8)) & 0xFF

    def read16(self, address):
        val32 = self.read32(address & ~3)
        return ((val32 >> 16) if (address & 2) else val32) & 0xFFFF

    def write8(self, address, value):
        aligned = address & ~3
        off = self._offset(aligned)
        old = self._regs.get(off, 0)
        bp = address & 3
        mask = 0xFF << (bp * 8)
        self.write32(aligned, (old & ~mask) | ((value & 0xFF) << (bp * 8)))

    def write16(self, address, value):
        aligned = address & ~3
        off = self._offset(aligned)
        old = self._regs.get(off, 0)
        if address & 2:
            new = (old & 0x0000FFFF) | ((value & 0xFFFF) << 16)
        else:
            new = (old & 0xFFFF0000) | (value & 0xFFFF)
        self.write32(aligned, new)

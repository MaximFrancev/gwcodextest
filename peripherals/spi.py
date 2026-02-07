"""
SPI — Serial Peripheral Interface (STM32H7B0)

SPI2 используется для инициализации дисплея.
Базовый адрес SPI2: 0x40003800
Размер: 0x400

Для эмуляции достаточно принимать записанные данные
и возвращать корректные статусные флаги.
"""


class SPI:
    """STM32H7B0 SPI peripheral."""

    SIZE = 0x400

    # Register offsets
    CR1     = 0x00
    CR2     = 0x04
    CFG1    = 0x08
    CFG2    = 0x0C
    IER     = 0x10
    SR      = 0x14
    IFCR    = 0x18
    TXDR    = 0x20
    RXDR    = 0x30
    CRCPOLY = 0x40
    TXCRC   = 0x44
    RXCRC   = 0x48
    UDRDR   = 0x4C
    I2SCFGR = 0x50

    def __init__(self, name, base_address):
        self.name = name
        self.base = base_address
        self.end = base_address + self.SIZE - 1
        self._regs = {}
        self.trace_enabled = False

        # TX/RX буферы для отладки
        self._tx_buffer = []
        self._rx_buffer = []

        self.reset()

    def reset(self):
        self._regs = {
            self.CR1:  0x00000000,
            self.CR2:  0x00000000,
            self.CFG1: 0x00070007,
            self.CFG2: 0x00000000,
            self.IER:  0x00000000,
            self.SR:   0x00001002,  # TXP=1 (TX ready), RXPLVL=0
            self.CRCPOLY: 0x00000107,
        }
        self._tx_buffer.clear()
        self._rx_buffer.clear()

    def contains(self, address):
        return self.base <= address <= self.end

    def _offset(self, address):
        return address - self.base

    def read32(self, address):
        off = self._offset(address)

        if off == self.SR:
            return self._read_sr()

        if off == self.RXDR:
            return self._read_rxdr()

        val = self._regs.get(off, 0)
        if self.trace_enabled:
            print(f"[{self.name}] Read +0x{off:02X} -> 0x{val:08X}")
        return val

    def write32(self, address, value):
        off = self._offset(address)
        value &= 0xFFFFFFFF

        if self.trace_enabled:
            print(f"[{self.name}] Write +0x{off:02X} = 0x{value:08X}")

        if off == self.TXDR:
            self._write_txdr(value)
            return

        if off == self.IFCR:
            # Interrupt flag clear
            sr = self._regs.get(self.SR, 0)
            self._regs[self.SR] = sr & ~value
            return

        self._regs[off] = value

    def read8(self, address):
        off = self._offset(address)
        if off == self.RXDR:
            if self._rx_buffer:
                return self._rx_buffer.pop(0)
            return 0
        val32 = self.read32(address & ~3)
        return (val32 >> ((address & 3) * 8)) & 0xFF

    def read16(self, address):
        val32 = self.read32(address & ~3)
        if address & 2:
            return (val32 >> 16) & 0xFFFF
        return val32 & 0xFFFF

    def write8(self, address, value):
        off = self._offset(address)
        if off == self.TXDR:
            self._tx_buffer.append(value & 0xFF)
            return
        aligned = address & ~3
        old_off = self._offset(aligned)
        old = self._regs.get(old_off, 0)
        bp = address & 3
        mask = 0xFF << (bp * 8)
        self.write32(aligned, (old & ~mask) | ((value & 0xFF) << (bp * 8)))

    def write16(self, address, value):
        off = self._offset(address)
        if off == self.TXDR:
            self._tx_buffer.append(value & 0xFFFF)
            return
        aligned = address & ~3
        old_off = self._offset(aligned)
        old = self._regs.get(old_off, 0)
        if address & 2:
            new = (old & 0x0000FFFF) | ((value & 0xFFFF) << 16)
        else:
            new = (old & 0xFFFF0000) | (value & 0xFFFF)
        self.write32(aligned, new)

    def _read_sr(self):
        """
        Status Register:
        Bit 0: RXP  — RX packet available
        Bit 1: TXP  — TX packet space available (always 1)
        Bit 3: EOT  — End of transfer
        Bit 5: OVR  — Overrun
        Bit 12: TXPLVL[1:0] — TX FIFO level
        """
        sr = self._regs.get(self.SR, 0)
        sr |= (1 << 1)   # TXP always ready
        sr |= (1 << 3)   # EOT = transfer done
        sr &= ~(1 << 5)  # No overrun
        return sr

    def _read_rxdr(self):
        """Чтение из RX — возвращаем 0 (нет данных от slave)."""
        return 0

    def _write_txdr(self, value):
        """Запись в TX — сохраняем для отладки."""
        self._tx_buffer.append(value)

    def __repr__(self):
        return f"{self.name}(TX_buf={len(self._tx_buffer)})"

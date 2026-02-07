"""
PWR — Power Control (STM32H7B0)

Базовый адрес: 0x58024800
Размер: 0x400

Firmware настраивает voltage scaling и ждёт VOSRDY.
Без корректного ответа — бесконечный цикл.
"""


class PWR:
    """STM32H7B0 Power Control."""

    BASE = 0x58024800
    SIZE = 0x400
    END = BASE + SIZE - 1

    # Register offsets
    CR1     = 0x00   # Power Control 1
    CSR1    = 0x04   # Power Control/Status 1
    CR2     = 0x08   # Power Control 2
    CR3     = 0x0C   # Power Control 3
    CPUCR   = 0x10   # CPU Power Control
    # 0x14 reserved
    SRDCR   = 0x18   # SRD Domain Power Control
    # 0x1C reserved
    WKUPCR  = 0x20   # Wakeup Clear
    WKUPFR  = 0x24   # Wakeup Flag
    WKUPEPR = 0x28   # Wakeup Enable and Polarity

    def __init__(self):
        self._regs = {}
        self.trace_enabled = False
        self.reset()

    def reset(self):
        self._regs = {
            self.CR1:     0x0000F000,  # VOS = Scale 3 (default)
            self.CSR1:    0x00004000,  # PVDO=0, ACTVOSRDY=1
            self.CR2:     0x00000000,
            self.CR3:     0x00000006,  # BYPASS=0, LDOEN=1, SCUEN=1
            self.CPUCR:   0x00000000,
            self.SRDCR:   0x00004000,  # VOSRDY=1
            self.WKUPCR:  0x00000000,
            self.WKUPFR:  0x00000000,
            self.WKUPEPR: 0x00000000,
        }

    def contains(self, address):
        return self.BASE <= address <= self.END

    def _offset(self, address):
        return address - self.BASE

    def read32(self, address):
        off = self._offset(address)
        val = self._read_register(off)
        if self.trace_enabled:
            name = self._reg_name(off)
            print(f"[PWR] Read {name} -> 0x{val:08X}")
        return val

    def write32(self, address, value):
        off = self._offset(address)
        if self.trace_enabled:
            name = self._reg_name(off)
            print(f"[PWR] Write {name} = 0x{value:08X}")
        self._write_register(off, value & 0xFFFFFFFF)

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

    def _read_register(self, offset):
        if offset == self.CSR1:
            return self._read_csr1()
        if offset == self.SRDCR:
            return self._read_srdcr()
        return self._regs.get(offset, 0)

    def _write_register(self, offset, value):
        if offset == self.CR1:
            self._write_cr1(value)
            return
        self._regs[offset] = value

    def _read_csr1(self):
        """
        CSR1: Power control/status.
        Bit 13: ACTVOSRDY — voltage scaling ready (всегда 1)
        Bit 14: ACTVOS[1:0] — отражает VOS из CR1
        Bit 16: PVDO
        """
        csr1 = self._regs.get(self.CSR1, 0)
        # Всегда ready
        csr1 |= (1 << 13)  # ACTVOSRDY
        
        # Отразить VOS из CR1
        cr1 = self._regs.get(self.CR1, 0)
        vos = (cr1 >> 14) & 0x3
        csr1 = (csr1 & ~(0x3 << 14)) | (vos << 14)
        
        return csr1

    def _read_srdcr(self):
        """
        SRDCR: SRD domain power control.
        Bit 13: VOSRDY — voltage output scaling ready (всегда 1)
        Bit [15:14]: VOS — отражает установленное значение
        """
        srdcr = self._regs.get(self.SRDCR, 0)
        srdcr |= (1 << 13)  # VOSRDY always ready
        return srdcr

    def _write_cr1(self, value):
        """CR1 write — сохраняем и обновляем VOS в SRDCR."""
        self._regs[self.CR1] = value
        # Копируем VOS в SRDCR
        vos = (value >> 14) & 0x3
        srdcr = self._regs.get(self.SRDCR, 0)
        srdcr = (srdcr & ~(0x3 << 14)) | (vos << 14)
        srdcr |= (1 << 13)  # VOSRDY
        self._regs[self.SRDCR] = srdcr

    def _reg_name(self, offset):
        names = {
            0x00: "CR1", 0x04: "CSR1", 0x08: "CR2", 0x0C: "CR3",
            0x10: "CPUCR", 0x18: "SRDCR",
            0x20: "WKUPCR", 0x24: "WKUPFR", 0x28: "WKUPEPR",
        }
        return names.get(offset, f"REG_0x{offset:03X}")

    def __repr__(self):
        cr1 = self._regs.get(self.CR1, 0)
        return f"PWR(CR1=0x{cr1:08X})"

"""
RCC — Reset and Clock Control (STM32H7B0)

Критически важная периферия: firmware первым делом настраивает тактирование.
Без корректных ответов RCC firmware зависнет в цикле ожидания PLL ready.

Базовый адрес: 0x58024400
Размер: 0x400

Ключевые регистры:
- CR: HSI/HSE/PLL enable + ready flags
- CFGR: System clock switch + status
- PLL1-3 DIVR/FRACR: PLL конфигурация
- AHB/APB prescalers
- Peripheral clock enable (AHBxENR, APBxENR)
"""


class RCC:
    """STM32H7B0 Reset and Clock Control."""

    BASE = 0x58024400
    SIZE = 0x400
    END = BASE + SIZE - 1

    # === Register offsets ===
    CR          = 0x00   # Clock Control Register
    HSICFGR     = 0x04   # HSI Configuration
    CRRCR       = 0x08   # Clock Recovery RC
    CSICFGR     = 0x0C   # CSI Configuration  
    CFGR        = 0x10   # Clock Configuration
    # 0x14 reserved
    CDCFGR1     = 0x18   # CD Domain Clock Configuration 1
    CDCFGR2     = 0x1C   # CD Domain Clock Configuration 2
    SRDCFGR     = 0x20   # SRD Domain Clock Configuration
    # 0x24 reserved
    PLLCKSELR   = 0x28   # PLL Clock Source Selection
    PLLCFGR     = 0x2C   # PLL Configuration
    PLL1DIVR    = 0x30   # PLL1 Dividers
    PLL1FRACR   = 0x34   # PLL1 Fractional
    PLL2DIVR    = 0x38   # PLL2 Dividers
    PLL2FRACR   = 0x3C   # PLL2 Fractional
    PLL3DIVR    = 0x40   # PLL3 Dividers
    PLL3FRACR   = 0x44   # PLL3 Fractional
    # 0x48-0x4C reserved
    CDCCIPR     = 0x50   # CD Domain Kernel Clock Config
    CDCCIP1R    = 0x54   # CD Domain Kernel Clock Config 1
    CDCCIP2R    = 0x58   # CD Domain Kernel Clock Config 2
    SRDCCIPR    = 0x5C   # SRD Domain Kernel Clock Config
    # 0x60-0x6C reserved
    CIER        = 0x70   # Clock Interrupt Enable
    CIFR        = 0x74   # Clock Interrupt Flag
    CICR        = 0x78   # Clock Interrupt Clear
    # 0x7C reserved
    BDCR        = 0x80   # Backup Domain Control
    CSR         = 0x84   # Clock Control and Status
    # 0x88 reserved
    AHB3RSTR    = 0x8C   # AHB3 Reset
    AHB1RSTR    = 0x90   # AHB1 Reset
    AHB2RSTR    = 0x94   # AHB2 Reset
    AHB4RSTR    = 0x98   # AHB4 Reset
    APB3RSTR    = 0x9C   # APB3 Reset
    APB1LRSTR   = 0xA0   # APB1L Reset
    APB1HRSTR   = 0xA4   # APB1H Reset
    APB2RSTR    = 0xA8   # APB2 Reset
    APB4RSTR    = 0xAC   # APB4 Reset
    # 0xB0 reserved  
    AHB3ENR     = 0xB4   # AHB3 Clock Enable
    AHB1ENR     = 0xB8   # AHB1 Clock Enable
    AHB2ENR     = 0xBC   # AHB2 Clock Enable
    AHB4ENR     = 0xC0   # AHB4 Clock Enable
    APB3ENR     = 0xC4   # APB3 Clock Enable
    APB1LENR    = 0xC8   # APB1L Clock Enable
    APB1HENR    = 0xCC   # APB1H Clock Enable
    APB2ENR     = 0xD0   # APB2 Clock Enable
    APB4ENR     = 0xD4   # APB4 Clock Enable
    # ... ещё LP enable, sleep mode registers и т.д.

    def __init__(self):
        self._regs = {}
        self.trace_enabled = False
        self.reset()

    def reset(self):
        """Сброс RCC в начальное состояние."""
        self._regs = {}
        
        # CR: HSI ON и READY по умолчанию после reset
        # Bit 0: HSION, Bit 2: HSIRDY
        # Bit 16: HSEON, Bit 17: HSERDY  
        # Bit 24: PLL1ON, Bit 25: PLL1RDY
        # Bit 26: PLL2ON, Bit 27: PLL2RDY
        # Bit 28: PLL3ON, Bit 29: PLL3RDY
        self._regs[self.CR] = 0x00000005  # HSION=1, HSIRDY=1

        # CFGR: HSI selected as system clock
        # Bits [2:0] SW: 000 = HSI
        # Bits [5:3] SWS: 000 = HSI selected  
        self._regs[self.CFGR] = 0x00000000

        # CSR: LSION reset value
        self._regs[self.CSR] = 0x00000000

        # BDCR
        self._regs[self.BDCR] = 0x00000000

        # PLLCKSELR: default PLL source = HSI
        self._regs[self.PLLCKSELR] = 0x02020200

        # PLLCFGR
        self._regs[self.PLLCFGR] = 0x01FF0000

        # CDCFGR1/2: no prescaling
        self._regs[self.CDCFGR1] = 0x00000000
        self._regs[self.CDCFGR2] = 0x00000000
        self._regs[self.SRDCFGR] = 0x00000000

    def contains(self, address):
        return self.BASE <= address <= self.END

    def _offset(self, address):
        return address - self.BASE

    def read32(self, address):
        off = self._offset(address)
        val = self._read_register(off)
        if self.trace_enabled:
            name = self._reg_name(off)
            print(f"[RCC] Read  {name} (+0x{off:03X}) -> 0x{val:08X}")
        return val

    def write32(self, address, value):
        off = self._offset(address)
        if self.trace_enabled:
            name = self._reg_name(off)
            print(f"[RCC] Write {name} (+0x{off:03X}) = 0x{value:08X}")
        self._write_register(off, value & 0xFFFFFFFF)

    def read8(self, address):
        val32 = self.read32(address & ~3)
        byte_pos = address & 3
        return (val32 >> (byte_pos * 8)) & 0xFF

    def read16(self, address):
        val32 = self.read32(address & ~3)
        if address & 2:
            return (val32 >> 16) & 0xFFFF
        return val32 & 0xFFFF

    def write8(self, address, value):
        aligned = address & ~3
        off = self._offset(aligned)
        old = self._regs.get(off, 0)
        byte_pos = address & 3
        mask = 0xFF << (byte_pos * 8)
        new = (old & ~mask) | ((value & 0xFF) << (byte_pos * 8))
        self.write32(aligned, new)

    def write16(self, address, value):
        aligned = address & ~3
        off = self._offset(aligned)
        old = self._regs.get(off, 0)
        if address & 2:
            new = (old & 0x0000FFFF) | ((value & 0xFFFF) << 16)
        else:
            new = (old & 0xFFFF0000) | (value & 0xFFFF)
        self.write32(aligned, new)

    # =============================================================
    # Register logic
    # =============================================================

    def _read_register(self, offset):
        """Чтение регистра с эмуляцией hardware-поведения."""
        
        if offset == self.CR:
            return self._read_cr()
        
        if offset == self.CFGR:
            return self._read_cfgr()

        return self._regs.get(offset, 0)

    def _write_register(self, offset, value):
        """Запись регистра с эмуляцией side-effects."""
        
        if offset == self.CR:
            self._write_cr(value)
            return
        
        if offset == self.CFGR:
            self._write_cfgr(value)
            return

        # Для остальных — просто сохраняем
        self._regs[offset] = value

    def _read_cr(self):
        """
        CR register read.
        Автоматически выставляем RDY флаги для включённых генераторов.
        Firmware ждёт эти флаги в цикле.
        """
        cr = self._regs.get(self.CR, 0)
        
        # HSI: если HSION (bit 0) → HSIRDY (bit 2)
        if cr & (1 << 0):
            cr |= (1 << 2)
        
        # CSI: если CSION (bit 7) → CSIRDY (bit 8)
        if cr & (1 << 7):
            cr |= (1 << 8)

        # HSI48: если HSI48ON (bit 12) → HSI48RDY (bit 13)
        if cr & (1 << 12):
            cr |= (1 << 13)
        
        # HSE: если HSEON (bit 16) → HSERDY (bit 17)
        if cr & (1 << 16):
            cr |= (1 << 17)
        
        # PLL1: если PLL1ON (bit 24) → PLL1RDY (bit 25)
        if cr & (1 << 24):
            cr |= (1 << 25)
        
        # PLL2: если PLL2ON (bit 26) → PLL2RDY (bit 27)
        if cr & (1 << 26):
            cr |= (1 << 27)
        
        # PLL3: если PLL3ON (bit 28) → PLL3RDY (bit 29)
        if cr & (1 << 28):
            cr |= (1 << 29)
        
        self._regs[self.CR] = cr
        return cr

    def _write_cr(self, value):
        """CR register write."""
        self._regs[self.CR] = value

    def _read_cfgr(self):
        """
        CFGR register read.
        SWS (bits [5:3]) отражает SW (bits [2:0]) — мгновенное переключение.
        """
        cfgr = self._regs.get(self.CFGR, 0)
        
        # SWS = SW (мгновенно отражаем выбор)
        sw = cfgr & 0x7
        cfgr = (cfgr & ~0x38) | (sw << 3)
        
        self._regs[self.CFGR] = cfgr
        return cfgr

    def _write_cfgr(self, value):
        """CFGR register write."""
        self._regs[self.CFGR] = value

    # =============================================================
    # Helper
    # =============================================================

    def _reg_name(self, offset):
        """Имя регистра по offset."""
        names = {
            0x00: "CR", 0x04: "HSICFGR", 0x08: "CRRCR", 0x0C: "CSICFGR",
            0x10: "CFGR", 0x18: "CDCFGR1", 0x1C: "CDCFGR2", 0x20: "SRDCFGR",
            0x28: "PLLCKSELR", 0x2C: "PLLCFGR",
            0x30: "PLL1DIVR", 0x34: "PLL1FRACR",
            0x38: "PLL2DIVR", 0x3C: "PLL2FRACR",
            0x40: "PLL3DIVR", 0x44: "PLL3FRACR",
            0x50: "CDCCIPR", 0x54: "CDCCIP1R", 0x58: "CDCCIP2R", 0x5C: "SRDCCIPR",
            0x70: "CIER", 0x74: "CIFR", 0x78: "CICR",
            0x80: "BDCR", 0x84: "CSR",
            0x8C: "AHB3RSTR", 0x90: "AHB1RSTR", 0x94: "AHB2RSTR",
            0x98: "AHB4RSTR", 0x9C: "APB3RSTR",
            0xA0: "APB1LRSTR", 0xA4: "APB1HRSTR", 0xA8: "APB2RSTR", 0xAC: "APB4RSTR",
            0xB4: "AHB3ENR", 0xB8: "AHB1ENR", 0xBC: "AHB2ENR",
            0xC0: "AHB4ENR", 0xC4: "APB3ENR",
            0xC8: "APB1LENR", 0xCC: "APB1HENR", 0xD0: "APB2ENR", 0xD4: "APB4ENR",
        }
        return names.get(offset, f"REG_0x{offset:03X}")

    def __repr__(self):
        cr = self._regs.get(self.CR, 0)
        cfgr = self._regs.get(self.CFGR, 0)
        return f"RCC(CR=0x{cr:08X}, CFGR=0x{cfgr:08X})"

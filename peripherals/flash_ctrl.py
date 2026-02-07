"""
Flash Interface Registers (STM32H7B0)

Базовый адрес: 0x52002000
Размер: 0x400

Firmware использует Flash interface для:
- Настройки wait states (latency) через ACR
- Проверки BSY флагов
- Опционально: program/erase (нам не нужно)

Ключевые регистры:
- ACR: Access Control (wait states, prefetch, etc.)
- SR: Status (BSY, error flags)
- CR: Control (lock/unlock, program, erase)
"""


class FlashInterface:
    """STM32H7B0 Embedded Flash Interface."""

    BASE = 0x52002000
    SIZE = 0x400
    END = BASE + SIZE - 1

    # Register offsets (Bank 1)
    ACR       = 0x00   # Access Control
    KEYR1     = 0x04   # Key (unlock)
    OPTKEYR   = 0x08   # Option Key
    CR1       = 0x0C   # Control Bank 1
    SR1       = 0x10   # Status Bank 1
    CCR1      = 0x14   # Clear Control Bank 1
    OPTCR     = 0x18   # Option Control
    OPTSR_CUR = 0x1C   # Option Status Current
    OPTSR_PRG = 0x20   # Option Status Program
    OPTCCR    = 0x24   # Option Clear Control
    # Bank 2 offset +0x100
    KEYR2     = 0x104
    CR2       = 0x10C
    SR2       = 0x110
    CCR2      = 0x114

    def __init__(self):
        self._regs = {}
        self.trace_enabled = False
        self.reset()

    def reset(self):
        self._regs = {
            self.ACR:       0x00000037,  # Default: LATENCY=7, WRHIGHFREQ=0
            self.CR1:       0x00000031,  # LOCK=1
            self.SR1:       0x00000000,  # No errors, not busy
            self.CCR1:      0x00000000,
            self.OPTCR:     0x00000001,  # OPTLOCK=1
            self.OPTSR_CUR: 0x00000000,
            self.OPTSR_PRG: 0x00000000,
            self.OPTCCR:    0x00000000,
            self.CR2:       0x00000031,  # LOCK=1
            self.SR2:       0x00000000,
            self.CCR2:      0x00000000,
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
            print(f"[FLASH_IF] Read {name} -> 0x{val:08X}")
        return val

    def write32(self, address, value):
        off = self._offset(address)
        if self.trace_enabled:
            name = self._reg_name(off)
            print(f"[FLASH_IF] Write {name} = 0x{value:08X}")
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
        # SR1/SR2: BSY всегда 0 (операция завершена)
        if offset == self.SR1 or offset == self.SR2:
            return 0x00000000  # Not busy, no errors

        return self._regs.get(offset, 0)

    def _write_register(self, offset, value):
        if offset == self.ACR:
            self._regs[self.ACR] = value
            return

        # KEYR: unlock sequence
        if offset == self.KEYR1:
            self._handle_unlock(1, value)
            return
        if offset == self.KEYR2:
            self._handle_unlock(2, value)
            return

        # CCR: write-1-to-clear for SR
        if offset == self.CCR1:
            self._regs[self.SR1] = self._regs.get(self.SR1, 0) & ~value
            return
        if offset == self.CCR2:
            self._regs[self.SR2] = self._regs.get(self.SR2, 0) & ~value
            return

        self._regs[offset] = value

    _unlock_state1 = 0
    _unlock_state2 = 0

    def _handle_unlock(self, bank, value):
        """Flash unlock sequence: KEY1=0x45670123, KEY2=0xCDEF89AB."""
        KEY1 = 0x45670123
        KEY2 = 0xCDEF89AB

        if bank == 1:
            if self._unlock_state1 == 0 and value == KEY1:
                self._unlock_state1 = 1
            elif self._unlock_state1 == 1 and value == KEY2:
                cr = self._regs.get(self.CR1, 0)
                cr &= ~(1 << 0)  # Clear LOCK bit
                self._regs[self.CR1] = cr
                self._unlock_state1 = 0
            else:
                self._unlock_state1 = 0
        else:
            if self._unlock_state2 == 0 and value == KEY1:
                self._unlock_state2 = 1
            elif self._unlock_state2 == 1 and value == KEY2:
                cr = self._regs.get(self.CR2, 0)
                cr &= ~(1 << 0)
                self._regs[self.CR2] = cr
                self._unlock_state2 = 0
            else:
                self._unlock_state2 = 0

    def _reg_name(self, offset):
        names = {
            0x00: "ACR", 0x04: "KEYR1", 0x08: "OPTKEYR",
            0x0C: "CR1", 0x10: "SR1", 0x14: "CCR1",
            0x18: "OPTCR", 0x1C: "OPTSR_CUR", 0x20: "OPTSR_PRG", 0x24: "OPTCCR",
            0x104: "KEYR2", 0x10C: "CR2", 0x110: "SR2", 0x114: "CCR2",
        }
        return names.get(offset, f"REG_0x{offset:03X}")

    def __repr__(self):
        acr = self._regs.get(self.ACR, 0)
        return f"FlashInterface(ACR=0x{acr:08X})"

"""
SAI — Serial Audio Interface (STM32H7B0)

SAI1 используется для вывода звука через NAU8315 усилитель.
Базовый адрес SAI1: 0x40015800
Размер: 0x400

Для начала — заглушка. Принимаем аудиоданные,
сохраняем для последующего вывода через pygame.
"""


class SAI:
    """STM32H7B0 Serial Audio Interface."""

    SIZE = 0x400

    # Register offsets (SAI block A, block B = +0x20)
    GCR    = 0x00   # Global Configuration
    # Block A
    ACR1   = 0x04   # A Configuration 1
    ACR2   = 0x08   # A Configuration 2
    AFRCR  = 0x0C   # A Frame Configuration
    ASLOTR = 0x10   # A Slot
    AIM    = 0x14   # A Interrupt Mask
    ASR    = 0x18   # A Status
    ACLRFR = 0x1C   # A Clear Flag
    ADR    = 0x20   # A Data
    # Block B
    BCR1   = 0x24   # B Configuration 1
    BCR2   = 0x28   # B Configuration 2
    BFRCR  = 0x2C   # B Frame Configuration
    BSLOTR = 0x30   # B Slot
    BIM    = 0x34   # B Interrupt Mask
    BSR    = 0x38   # B Status
    BCLRFR = 0x3C   # B Clear Flag
    BDR    = 0x40   # B Data
    # PDMCR/PDMDLY
    PDMCR  = 0x44
    PDMDLY = 0x48

    def __init__(self, name, base_address):
        self.name = name
        self.base = base_address
        self.end = base_address + self.SIZE - 1
        self._regs = {}
        self.trace_enabled = False

        # Аудио буфер для последующего воспроизведения
        self._audio_buffer = []
        self._max_buffer = 48000 * 2  # ~1 секунда стерео

        self.reset()

    def reset(self):
        self._regs = {
            self.GCR:   0x00000000,
            self.ACR1:  0x00000040,
            self.ACR2:  0x00000000,
            self.AFRCR: 0x00000007,
            self.ASLOTR: 0x00000000,
            self.AIM:   0x00000000,
            self.ASR:   0x00000008,  # FREQ flag
            self.ADR:   0x00000000,
            self.BCR1:  0x00000040,
            self.BCR2:  0x00000000,
            self.BSR:   0x00000008,
        }
        self._audio_buffer.clear()

    def contains(self, address):
        return self.base <= address <= self.end

    def _offset(self, address):
        return address - self.base

    def read32(self, address):
        off = self._offset(address)

        if off == self.ASR:
            return self._read_asr()
        if off == self.BSR:
            return self._read_bsr()

        val = self._regs.get(off, 0)
        if self.trace_enabled:
            print(f"[{self.name}] Read +0x{off:02X} -> 0x{val:08X}")
        return val

    def write32(self, address, value):
        off = self._offset(address)
        value &= 0xFFFFFFFF

        if self.trace_enabled:
            print(f"[{self.name}] Write +0x{off:02X} = 0x{value:08X}")

        if off == self.ADR:
            self._write_audio(value)
            return

        if off == self.BDR:
            self._write_audio(value)
            return

        if off == self.ACLRFR:
            sr = self._regs.get(self.ASR, 0)
            self._regs[self.ASR] = sr & ~value
            return

        if off == self.BCLRFR:
            sr = self._regs.get(self.BSR, 0)
            self._regs[self.BSR] = sr & ~value
            return

        self._regs[off] = value

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

    def _read_asr(self):
        """Block A Status: FIFO ready, no errors."""
        sr = self._regs.get(self.ASR, 0)
        sr &= ~(1 << 3)  # Clear FREQ (FIFO request)
        sr |= (1 << 1)   # FLVL: FIFO not full → can accept data
        return sr

    def _read_bsr(self):
        sr = self._regs.get(self.BSR, 0)
        sr &= ~(1 << 3)
        sr |= (1 << 1)
        return sr

    def _write_audio(self, value):
        """Принять аудио сэмпл."""
        if len(self._audio_buffer) < self._max_buffer:
            self._audio_buffer.append(value)

    def get_audio_samples(self, count=None):
        """Забрать аудио сэмплы для воспроизведения."""
        if count is None:
            samples = self._audio_buffer[:]
            self._audio_buffer.clear()
            return samples
        samples = self._audio_buffer[:count]
        self._audio_buffer = self._audio_buffer[count:]
        return samples

    def __repr__(self):
        return f"{self.name}(buf={len(self._audio_buffer)})"

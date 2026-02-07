"""
LTDC — LCD-TFT Display Controller (STM32H7B0)

Базовый адрес: 0x50001000
Размер: 0x1000

Game & Watch использует LTDC для вывода на 320x240 дисплей.
Контроллер читает фреймбуфер из RAM и генерирует LCD сигналы.

Ключевое для эмуляции:
- Определить адрес фреймбуфера (Layer1 CFBAR)
- Определить формат пикселей (Layer1 PFCR)
- Отслеживать VSYNC для синхронизации рендеринга
- Размеры окна для определения реального разрешения

Регистры (основные):
  0x008 SSCR   — Synchronization Size Config
  0x00C BPCR   — Back Porch Config
  0x010 AWCR   — Active Width Config
  0x014 TWCR   — Total Width Config
  0x018 GCR    — Global Control
  0x024 SRCR   — Shadow Reload Config
  0x02C BCCR   — Background Color Config
  0x034 IER    — Interrupt Enable
  0x038 ISR    — Interrupt Status
  0x03C ICR    — Interrupt Clear
  0x040 LIPCR  — Line Interrupt Position Config
  0x044 CPSR   — Current Position Status
  0x048 CDSR   — Current Display Status

Layer1 registers (offset 0x084):
  0x084 L1CR    — Layer 1 Control
  0x088 L1WHPCR — Layer 1 Window H Position
  0x08C L1WVPCR — Layer 1 Window V Position
  0x090 L1CKCR  — Layer 1 Color Keying
  0x094 L1PFCR  — Layer 1 Pixel Format
  0x098 L1CACR  — Layer 1 Constant Alpha
  0x09C L1DCCR  — Layer 1 Default Color
  0x0A0 L1BFCR  — Layer 1 Blending Factors
  0x0AC L1CFBAR — Layer 1 Color Frame Buffer Address
  0x0B0 L1CFBLR — Layer 1 Color FB Length
  0x0B4 L1CFBLNR— Layer 1 Color FB Line Number
  0x0C4 L1CLUTWR— Layer 1 CLUT Write

Layer2 registers (offset 0x104):
  Same structure, +0x80 from Layer1
"""


class LTDCLayer:
    """Один слой LTDC."""

    def __init__(self, name, base_offset):
        self.name = name
        self.base_offset = base_offset
        self._regs = {}
        self.reset()

    def reset(self):
        self._regs = {}

    def read(self, offset):
        local = offset - self.base_offset
        return self._regs.get(local, 0)

    def write(self, offset, value):
        local = offset - self.base_offset
        self._regs[local] = value & 0xFFFFFFFF

    @property
    def enabled(self):
        """Layer enable bit (CR bit 0)."""
        cr = self._regs.get(0x00, 0)
        return bool(cr & 1)

    @property
    def framebuffer_address(self):
        """CFBAR — адрес фреймбуфера."""
        return self._regs.get(0x28, 0)  # offset 0x28 from layer base = CFBAR

    @property
    def pixel_format(self):
        """
        PFCR — Pixel Format.
        0: ARGB8888
        1: RGB888
        2: RGB565
        3: ARGB1555
        4: ARGB4444
        5: L8 (8-bit luminance)
        6: AL44
        7: AL88
        """
        return self._regs.get(0x10, 0) & 0x7  # PFCR offset from layer base

    @property
    def pixel_size(self):
        """Размер пикселя в байтах."""
        sizes = {0: 4, 1: 3, 2: 2, 3: 2, 4: 2, 5: 1, 6: 1, 7: 2}
        return sizes.get(self.pixel_format, 4)

    @property
    def window_h(self):
        """Горизонтальное окно (start, stop)."""
        whpcr = self._regs.get(0x04, 0)  # WHPCR
        start = whpcr & 0xFFF
        stop = (whpcr >> 16) & 0xFFF
        return start, stop

    @property
    def window_v(self):
        """Вертикальное окно (start, stop)."""
        wvpcr = self._regs.get(0x08, 0)  # WVPCR
        start = wvpcr & 0x7FF
        stop = (wvpcr >> 16) & 0x7FF
        return start, stop

    @property
    def fb_line_length(self):
        """CFBLR — длина строки в байтах (+ pitch)."""
        cfblr = self._regs.get(0x2C, 0)
        line_length = cfblr & 0x1FFF
        pitch = (cfblr >> 16) & 0x1FFF
        return line_length, pitch

    @property
    def fb_line_number(self):
        """CFBLNR — количество строк."""
        return self._regs.get(0x30, 0) & 0x7FF


class LTDC:
    """STM32H7B0 LCD-TFT Display Controller."""

    BASE = 0x50001000
    SIZE = 0x1000
    END = BASE + SIZE - 1

    # Global register offsets
    SSCR  = 0x008
    BPCR  = 0x00C
    AWCR  = 0x010
    TWCR  = 0x014
    GCR   = 0x018
    SRCR  = 0x024
    BCCR  = 0x02C
    IER   = 0x034
    ISR   = 0x038
    ICR   = 0x03C
    LIPCR = 0x040
    CPSR  = 0x044
    CDSR  = 0x048

    # Layer offsets
    L1_BASE = 0x084
    L1_END  = 0x0D0
    L2_BASE = 0x104
    L2_END  = 0x150

    def __init__(self):
        self._regs = {}
        self.layer1 = LTDCLayer("L1", self.L1_BASE)
        self.layer2 = LTDCLayer("L2", self.L2_BASE)
        self.trace_enabled = False

        # VSYNC счётчик для синхронизации
        self._vsync_count = 0
        self._tick_count = 0

        self.reset()

    def reset(self):
        self._regs = {
            self.GCR:  0x00002220,  # LTDC disabled
            self.SSCR: 0x00000000,
            self.BPCR: 0x00000000,
            self.AWCR: 0x00000000,
            self.TWCR: 0x00000000,
            self.SRCR: 0x00000000,
            self.BCCR: 0x00000000,
            self.IER:  0x00000000,
            self.ISR:  0x00000000,
            self.ICR:  0x00000000,
            self.LIPCR: 0x00000000,
            self.CPSR: 0x00000000,
            self.CDSR: 0x0000000F,  # VSYNCS=1, HSYNCS=1, VDES=1, HDES=1
        }
        self.layer1.reset()
        self.layer2.reset()

    def contains(self, address):
        return self.BASE <= address <= self.END

    def _offset(self, address):
        return address - self.BASE

    def read32(self, address):
        off = self._offset(address)

        # Layer 1
        if self.L1_BASE <= off <= self.L1_END:
            val = self.layer1.read(off)
            if self.trace_enabled:
                print(f"[LTDC] Read L1+0x{off - self.L1_BASE:02X} -> 0x{val:08X}")
            return val

        # Layer 2
        if self.L2_BASE <= off <= self.L2_END:
            val = self.layer2.read(off)
            if self.trace_enabled:
                print(f"[LTDC] Read L2+0x{off - self.L2_BASE:02X} -> 0x{val:08X}")
            return val

        # ISR: эмулируем VSYNC
        if off == self.ISR:
            return self._read_isr()

        # CDSR: текущий статус дисплея
        if off == self.CDSR:
            return self._read_cdsr()

        val = self._regs.get(off, 0)
        if self.trace_enabled:
            print(f"[LTDC] Read +0x{off:03X} -> 0x{val:08X}")
        return val

    def write32(self, address, value):
        off = self._offset(address)
        value &= 0xFFFFFFFF

        if self.trace_enabled:
            print(f"[LTDC] Write +0x{off:03X} = 0x{value:08X}")

        # Layer 1
        if self.L1_BASE <= off <= self.L1_END:
            self.layer1.write(off, value)
            return

        # Layer 2
        if self.L2_BASE <= off <= self.L2_END:
            self.layer2.write(off, value)
            return

        # ICR: write-1-to-clear ISR
        if off == self.ICR:
            isr = self._regs.get(self.ISR, 0)
            self._regs[self.ISR] = isr & ~value
            return

        # SRCR: shadow reload (мгновенно)
        if off == self.SRCR:
            # Bit 0: IMR (immediate reload) — мы делаем всё мгновенно
            # Bit 1: VBR (vertical blanking reload)
            self._regs[self.SRCR] = 0  # Сброс после reload
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
        old = self.read32(aligned)
        bp = address & 3
        mask = 0xFF << (bp * 8)
        self.write32(aligned, (old & ~mask) | ((value & 0xFF) << (bp * 8)))

    def write16(self, address, value):
        aligned = address & ~3
        old = self.read32(aligned)
        if address & 2:
            new = (old & 0x0000FFFF) | ((value & 0xFFFF) << 16)
        else:
            new = (old & 0xFFFF0000) | (value & 0xFFFF)
        self.write32(aligned, new)

    # === Display status emulation ===

    def _read_isr(self):
        """ISR: периодически генерируем VSYNC флаг."""
        isr = self._regs.get(self.ISR, 0)
        # Бит 0: Line interrupt flag
        # Бит 3: Register reload flag  
        return isr

    def _read_cdsr(self):
        """
        CDSR: Current Display Status Register.
        Эмулируем активный дисплей.
        """
        # Bit 0: VDES (vertical data enable)
        # Bit 1: HDES (horizontal data enable)
        # Bit 2: VSYNCS (vertical sync)
        # Bit 3: HSYNCS (horizontal sync)
        return 0x0000000F  # Всё активно

    def tick(self, cycles=1, cycles_per_vsync=4096):
        """
        Вызывается периодически для генерации VSYNC прерывания.
        Возвращает True если произошёл VSYNC.
        """
        self._tick_count += max(int(cycles), 1)

        # Эмулируем ~60fps: VSYNC каждые cycles_per_vsync CPU cycles.
        if self._tick_count >= cycles_per_vsync:
            self._tick_count = 0
            self._vsync_count += 1

            ier = self._regs.get(self.IER, 0)
            if ier & 1:  # Line interrupt enabled
                isr = self._regs.get(self.ISR, 0)
                self._regs[self.ISR] = isr | 1  # Set line interrupt flag
                return True

        return False

    # === Framebuffer info ===

    @property
    def enabled(self):
        """LTDC enabled (GCR bit 0)."""
        return bool(self._regs.get(self.GCR, 0) & 1)

    def get_framebuffer_info(self):
        """Получить информацию о фреймбуфере для рендеринга."""
        if not self.layer1.enabled:
            return None

        return {
            'address': self.layer1.framebuffer_address,
            'pixel_format': self.layer1.pixel_format,
            'pixel_size': self.layer1.pixel_size,
            'window_h': self.layer1.window_h,
            'window_v': self.layer1.window_v,
            'line_length': self.layer1.fb_line_length,
            'line_number': self.layer1.fb_line_number,
        }

    def get_display_size(self):
        """Вычислить размер дисплея из AWCR и BPCR."""
        awcr = self._regs.get(self.AWCR, 0)
        bpcr = self._regs.get(self.BPCR, 0)

        aw = ((awcr >> 16) & 0xFFF) - ((bpcr >> 16) & 0xFFF)
        ah = (awcr & 0x7FF) - (bpcr & 0x7FF)

        if aw <= 0 or ah <= 0:
            return 320, 240  # Default G&W resolution

        return aw, ah

    def __repr__(self):
        en = "ON" if self.enabled else "OFF"
        fb = self.layer1.framebuffer_address
        fmt = self.layer1.pixel_format
        return f"LTDC({en}, FB=0x{fb:08X}, fmt={fmt})"

"""
TIM — General Purpose Timers (STM32H7B0)

Firmware может использовать таймеры для:
- Генерации временных задержек
- PWM для подсветки дисплея
- Периодических прерываний

Базовые адреса:
  TIM1:  0x40010000 (Advanced)
  TIM2:  0x40000000 (General purpose, 32-bit)
  TIM3:  0x40000400 (General purpose, 16-bit)
  TIM4:  0x40000800
  TIM5:  0x40000C00
  TIM6:  0x40001000 (Basic)
  TIM7:  0x40001400 (Basic)

Размер каждого: 0x400

Для эмуляции — базовая функциональность:
- Счётчик (CNT) считает вверх
- При достижении ARR — переполнение, UIF флаг
- Опционально генерируется прерывание
"""


class Timer:
    """STM32H7B0 General Purpose Timer."""

    SIZE = 0x400

    # Register offsets (общие для большинства таймеров)
    CR1   = 0x00   # Control 1
    CR2   = 0x04   # Control 2
    SMCR  = 0x08   # Slave Mode Control
    DIER  = 0x0C   # DMA/Interrupt Enable
    SR    = 0x10   # Status
    EGR   = 0x14   # Event Generation
    CCMR1 = 0x18   # Capture/Compare Mode 1
    CCMR2 = 0x1C   # Capture/Compare Mode 2
    CCER  = 0x20   # Capture/Compare Enable
    CNT   = 0x24   # Counter
    PSC   = 0x28   # Prescaler
    ARR   = 0x2C   # Auto-Reload
    RCR   = 0x30   # Repetition Counter (advanced timers)
    CCR1  = 0x34   # Capture/Compare 1
    CCR2  = 0x38   # Capture/Compare 2
    CCR3  = 0x3C   # Capture/Compare 3
    CCR4  = 0x40   # Capture/Compare 4
    BDTR  = 0x44   # Break and Dead-Time (advanced)
    DCR   = 0x48   # DMA Control
    DMAR  = 0x4C   # DMA Address for burst
    # TIM2/TIM5 specific
    AF1   = 0x60   # Alternate Function 1
    AF2   = 0x64   # Alternate Function 2
    TISEL = 0x68   # Timer Input Selection

    def __init__(self, name, base_address, bits=16, exc_manager=None, irq_number=None):
        """
        name: "TIM1", "TIM2", etc.
        base_address: базовый адрес
        bits: 16 или 32 (TIM2/TIM5 = 32-bit)
        exc_manager: для генерации прерываний
        irq_number: номер прерывания (exception number = irq + 16)
        """
        self.name = name
        self.base = base_address
        self.end = base_address + self.SIZE - 1
        self.bits = bits
        self.exc_manager = exc_manager
        self.irq_number = irq_number

        self._counter_mask = 0xFFFFFFFF if bits == 32 else 0xFFFF

        self._regs = {}
        self.trace_enabled = False

        # Внутренний prescaler счётчик
        self._psc_counter = 0

        self.reset()

    def reset(self):
        self._regs = {
            self.CR1:   0x00000000,
            self.CR2:   0x00000000,
            self.SMCR:  0x00000000,
            self.DIER:  0x00000000,
            self.SR:    0x00000000,
            self.CCMR1: 0x00000000,
            self.CCMR2: 0x00000000,
            self.CCER:  0x00000000,
            self.CNT:   0x00000000,
            self.PSC:   0x00000000,
            self.ARR:   0x0000FFFF if self.bits == 16 else 0xFFFFFFFF,
            self.RCR:   0x00000000,
            self.CCR1:  0x00000000,
            self.CCR2:  0x00000000,
            self.CCR3:  0x00000000,
            self.CCR4:  0x00000000,
            self.BDTR:  0x00000000,
        }
        self._psc_counter = 0

    def contains(self, address):
        return self.base <= address <= self.end

    def _offset(self, address):
        return address - self.base

    # === Read ===

    def read32(self, address):
        off = self._offset(address)
        val = self._regs.get(off, 0)

        if off == self.CNT:
            val &= self._counter_mask

        if self.trace_enabled:
            name = self._reg_name(off)
            print(f"[{self.name}] Read {name} -> 0x{val:08X}")
        return val

    def read16(self, address):
        val32 = self.read32(address & ~3)
        if address & 2:
            return (val32 >> 16) & 0xFFFF
        return val32 & 0xFFFF

    def read8(self, address):
        val32 = self.read32(address & ~3)
        return (val32 >> ((address & 3) * 8)) & 0xFF

    # === Write ===

    def write32(self, address, value):
        off = self._offset(address)
        value &= 0xFFFFFFFF

        if self.trace_enabled:
            name = self._reg_name(off)
            print(f"[{self.name}] Write {name} = 0x{value:08X}")

        if off == self.SR:
            # SR: write-0-to-clear (не write-1-to-clear!)
            self._regs[self.SR] = self._regs.get(self.SR, 0) & value
            return

        if off == self.EGR:
            self._handle_egr(value)
            return

        if off == self.CNT:
            self._regs[self.CNT] = value & self._counter_mask
            return

        self._regs[off] = value

    def write16(self, address, value):
        off = self._offset(address & ~3)
        # Для таймеров 16-bit регистры — просто записываем младшие 16 бит
        if not (address & 2):
            old = self._regs.get(off, 0)
            new = (old & 0xFFFF0000) | (value & 0xFFFF)
            self.write32(address & ~3, new)
        else:
            old = self._regs.get(off, 0)
            new = (old & 0x0000FFFF) | ((value & 0xFFFF) << 16)
            self.write32(address & ~3, new)

    def write8(self, address, value):
        aligned = address & ~3
        off = self._offset(aligned)
        old = self._regs.get(off, 0)
        bp = address & 3
        mask = 0xFF << (bp * 8)
        self.write32(aligned, (old & ~mask) | ((value & 0xFF) << (bp * 8)))

    # === EGR (Event Generation) ===

    def _handle_egr(self, value):
        """EGR — запись бита вызывает событие."""
        if value & 1:  # UG: Update generation
            # Перезагрузить CNT, PSC, установить UIF
            self._regs[self.CNT] = 0
            self._psc_counter = 0
            sr = self._regs.get(self.SR, 0)
            self._regs[self.SR] = sr | 1  # UIF

    # === Tick (вызывается каждый цикл CPU) ===

    def tick(self, cycles=1):
        """
        Обновить таймер.
        Возвращает True если произошло update-прерывание.
        """
        cr1 = self._regs.get(self.CR1, 0)
        if not (cr1 & 1):  # CEN (Counter Enable)
            return False

        psc = self._regs.get(self.PSC, 0)
        arr = self._regs.get(self.ARR, 0xFFFF) & self._counter_mask
        cnt = self._regs.get(self.CNT, 0) & self._counter_mask
        dier = self._regs.get(self.DIER, 0)

        fired = False

        for _ in range(cycles):
            self._psc_counter += 1
            if self._psc_counter > psc:
                self._psc_counter = 0

                # Направление счёта
                if cr1 & (1 << 4):  # DIR: 1 = downcounting
                    if cnt == 0:
                        cnt = arr
                        self._regs[self.SR] = self._regs.get(self.SR, 0) | 1
                        fired = True
                    else:
                        cnt -= 1
                else:
                    # Upcounting
                    if cnt >= arr:
                        cnt = 0
                        self._regs[self.SR] = self._regs.get(self.SR, 0) | 1  # UIF
                        fired = True

                        # One-pulse mode
                        if cr1 & (1 << 3):  # OPM
                            cr1 &= ~1  # Disable counter
                            self._regs[self.CR1] = cr1
                    else:
                        cnt += 1

        self._regs[self.CNT] = cnt & self._counter_mask

        # Генерировать прерывание
        if fired and (dier & 1):  # UIE (Update Interrupt Enable)
            if self.exc_manager and self.irq_number is not None:
                exc_num = self.irq_number + 16
                self.exc_manager.set_pending(exc_num)

        return fired

    # === Capture/Compare check ===

    def check_cc(self):
        """Проверить capture/compare каналы (упрощённо)."""
        cnt = self._regs.get(self.CNT, 0)
        sr = self._regs.get(self.SR, 0)

        for i, ccr_off in enumerate([self.CCR1, self.CCR2, self.CCR3, self.CCR4]):
            ccr = self._regs.get(ccr_off, 0)
            if cnt == ccr:
                sr |= (1 << (i + 1))  # CC1IF, CC2IF, CC3IF, CC4IF

        self._regs[self.SR] = sr

    # === Info ===

    @property
    def enabled(self):
        return bool(self._regs.get(self.CR1, 0) & 1)

    @property
    def counter(self):
        return self._regs.get(self.CNT, 0) & self._counter_mask

    def _reg_name(self, offset):
        names = {
            0x00: "CR1", 0x04: "CR2", 0x08: "SMCR", 0x0C: "DIER",
            0x10: "SR", 0x14: "EGR", 0x18: "CCMR1", 0x1C: "CCMR2",
            0x20: "CCER", 0x24: "CNT", 0x28: "PSC", 0x2C: "ARR",
            0x30: "RCR", 0x34: "CCR1", 0x38: "CCR2", 0x3C: "CCR3",
            0x40: "CCR4", 0x44: "BDTR", 0x48: "DCR", 0x4C: "DMAR",
            0x60: "AF1", 0x64: "AF2", 0x68: "TISEL",
        }
        return names.get(offset, f"REG_0x{offset:03X}")

    def __repr__(self):
        en = "ON" if self.enabled else "OFF"
        cnt = self.counter
        arr = self._regs.get(self.ARR, 0)
        return f"{self.name}({en}, CNT=0x{cnt:X}, ARR=0x{arr:X})"

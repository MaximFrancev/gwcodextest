"""
SysTick — System Timer (ARM Cortex-M7)

Встроен в ядро Cortex-M, не является периферией STM32.
Адреса: 0xE000E010 - 0xE000E01F

Используется firmware для задержек и периодических прерываний.
Таймер считает вниз от LOAD до 0, при достижении 0:
- Устанавливает COUNTFLAG
- Если TICKINT=1, генерирует исключение SysTick (#15)
- Перезагружается значением LOAD

Регистры:
  0xE000E010 CTRL  — Control and Status
  0xE000E014 LOAD  — Reload Value (24 бит)
  0xE000E018 VAL   — Current Value (24 бит)
  0xE000E01C CALIB — Calibration Value

CTRL bits:
  [0]  ENABLE    — включить таймер
  [1]  TICKINT   — генерировать прерывание при 0
  [2]  CLKSOURCE — 0=external ref, 1=processor clock
  [16] COUNTFLAG — был ли переход через 0 (очищается при чтении)
"""


class SysTick:
    """ARM Cortex-M7 SysTick Timer."""

    BASE = 0xE000E010
    SIZE = 0x10
    END = BASE + SIZE - 1

    # Register offsets
    CTRL_OFF  = 0x00
    LOAD_OFF  = 0x04
    VAL_OFF   = 0x08
    CALIB_OFF = 0x0C

    # Absolute addresses
    CTRL_ADDR  = 0xE000E010
    LOAD_ADDR  = 0xE000E014
    VAL_ADDR   = 0xE000E018
    CALIB_ADDR = 0xE000E01C

    def __init__(self, exc_manager=None):
        """
        exc_manager: ExceptionManager для генерации SysTick прерывания.
        """
        self.exc_manager = exc_manager
        self.trace_enabled = False

        self._ctrl = 0x00000004    # CLKSOURCE=1 (processor clock) по умолчанию
        self._load = 0x00000000    # Reload value
        self._val = 0x00000000     # Current value
        self._calib = 0x80000000   # NOREF=1, TENMS=0 (не калиброван)

        # Счётчик для downscaling (SysTick каждый N-й цикл CPU)
        # На реальном MCU SysTick тикает каждый такт CPU (280MHz)
        # В эмуляторе мы вызываем tick() каждый цикл
        self._prescale_counter = 0
        self._prescale = 1  # 1 = каждый вызов tick()

    def reset(self):
        """Сброс SysTick."""
        self._ctrl = 0x00000004
        self._load = 0x00000000
        self._val = 0x00000000

    def contains(self, address):
        return self.BASE <= address <= self.END

    def _offset(self, address):
        return address - self.BASE

    # === Read ===

    def read32(self, address):
        off = self._offset(address)

        if off == self.CTRL_OFF:
            return self._read_ctrl()
        elif off == self.LOAD_OFF:
            return self._load & 0x00FFFFFF
        elif off == self.VAL_OFF:
            return self._val & 0x00FFFFFF
        elif off == self.CALIB_OFF:
            return self._calib

        return 0

    def read8(self, address):
        val32 = self.read32(address & ~3)
        return (val32 >> ((address & 3) * 8)) & 0xFF

    def read16(self, address):
        val32 = self.read32(address & ~3)
        if address & 2:
            return (val32 >> 16) & 0xFFFF
        return val32 & 0xFFFF

    # === Write ===

    def write32(self, address, value):
        off = self._offset(address)
        value &= 0xFFFFFFFF

        if off == self.CTRL_OFF:
            self._write_ctrl(value)
        elif off == self.LOAD_OFF:
            self._load = value & 0x00FFFFFF
        elif off == self.VAL_OFF:
            # Запись любого значения очищает VAL и COUNTFLAG
            self._val = 0
            self._ctrl &= ~(1 << 16)
        # CALIB is read-only

    def write8(self, address, value):
        # Simplified: full 32-bit write
        self.write32(address & ~3, value & 0xFF)

    def write16(self, address, value):
        self.write32(address & ~3, value & 0xFFFF)

    # === Control register ===

    def _read_ctrl(self):
        """
        Чтение CTRL очищает COUNTFLAG (bit 16).
        """
        val = self._ctrl
        # Очистить COUNTFLAG после чтения
        self._ctrl &= ~(1 << 16)
        return val

    def _write_ctrl(self, value):
        """Запись в CTRL."""
        old_enable = self._ctrl & 1
        self._ctrl = value & 0x00010007  # Только значимые биты

        # Если только что включили — сбросить VAL
        new_enable = self._ctrl & 1
        if not old_enable and new_enable:
            self._val = self._load

        if self.trace_enabled:
            en = "ON" if (self._ctrl & 1) else "OFF"
            tickint = "IRQ" if (self._ctrl & 2) else "noIRQ"
            print(f"[SysTick] CTRL={en} {tickint} LOAD=0x{self._load:06X}")

    # === Tick (вызывается каждый цикл CPU) ===

    def tick(self, cycles=1):
        """
        Обновить SysTick на указанное количество циклов.
        
        Возвращает True если произошло прерывание SysTick.
        """
        if not (self._ctrl & 1):  # ENABLE
            return False

        fired = False

        for _ in range(cycles):
            if self._val > 0:
                self._val -= 1
            else:
                # Достигли 0 — перезагрузка
                self._val = self._load & 0x00FFFFFF

                # Установить COUNTFLAG
                self._ctrl |= (1 << 16)

                # Генерировать прерывание если TICKINT=1
                if self._ctrl & (1 << 1):
                    if self.exc_manager:
                        from cpu.exceptions import ExceptionType
                        self.exc_manager.set_pending(ExceptionType.SYSTICK)
                    fired = True

        return fired

    # === Info ===

    @property
    def enabled(self):
        return bool(self._ctrl & 1)

    @property
    def tickint(self):
        return bool(self._ctrl & 2)

    @property
    def current(self):
        return self._val

    @property
    def reload_value(self):
        return self._load

    def __repr__(self):
        en = "ON" if self.enabled else "OFF"
        return (f"SysTick({en}, LOAD=0x{self._load:06X}, "
                f"VAL=0x{self._val:06X}, TICKINT={self.tickint})")

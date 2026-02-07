"""
GPIO — General Purpose I/O (STM32H7B0)

5 портов используются в Game & Watch: GPIOA-GPIOE.
Каждый порт — 0x400 байт адресного пространства.

Ключевое для G&W:
- Кнопки подключены к GPIO портам C и D (входы)
- LCD сигналы через alternate function
- Некоторые пины — general purpose output

Базовые адреса:
  GPIOA: 0x58020000
  GPIOB: 0x58020400
  GPIOC: 0x58020800
  GPIOD: 0x58020C00
  GPIOE: 0x58021000

Регистры каждого порта (offset от базы):
  0x00 MODER   — Mode register
  0x04 OTYPER  — Output type
  0x08 OSPEEDR — Output speed
  0x0C PUPDR   — Pull-up/pull-down
  0x10 IDR     — Input data (read-only, отражает состояние пинов)
  0x14 ODR     — Output data
  0x18 BSRR    — Bit set/reset (write-only)
  0x1C LCKR    — Lock
  0x20 AFRL    — Alternate function low (pins 0-7)
  0x24 AFRH    — Alternate function high (pins 8-15)
"""


class GPIOPort:
    """Один GPIO порт (16 пинов)."""

    # Register offsets
    MODER   = 0x00
    OTYPER  = 0x04
    OSPEEDR = 0x08
    PUPDR   = 0x0C
    IDR     = 0x10
    ODR     = 0x14
    BSRR    = 0x18
    LCKR    = 0x1C
    AFRL    = 0x20
    AFRH    = 0x24

    SIZE = 0x400

    def __init__(self, name, base_address, default_moder=0x00000000):
        """
        name: "GPIOA", "GPIOB", etc.
        base_address: базовый адрес порта
        default_moder: начальное значение MODER (зависит от порта)
        """
        self.name = name
        self.base = base_address
        self.end = base_address + self.SIZE - 1

        self._regs = {}
        self._default_moder = default_moder

        # Внешние входные состояния (эмуляция кнопок и т.д.)
        # Bit mask: bit N = состояние пина N
        self._external_input = 0xFFFF  # По умолчанию все HIGH (pull-up)

        # Callback при изменении ODR (для отладки/дисплея)
        self.on_output_change = None

        self.trace_enabled = False
        self.reset()

    def reset(self):
        """Сброс в начальное состояние."""
        self._regs = {
            self.MODER:   self._default_moder,
            self.OTYPER:  0x00000000,
            self.OSPEEDR: 0x00000000,
            self.PUPDR:   0x00000000,
            self.IDR:     0x0000FFFF,
            self.ODR:     0x00000000,
            self.LCKR:    0x00000000,
            self.AFRL:    0x00000000,
            self.AFRH:    0x00000000,
        }

    def contains(self, address):
        return self.base <= address <= self.end

    def _offset(self, address):
        return address - self.base

    # === Внешний вход (кнопки) ===

    def set_pin(self, pin, high):
        """Установить состояние входного пина (для эмуляции кнопок)."""
        if high:
            self._external_input |= (1 << pin)
        else:
            self._external_input &= ~(1 << pin)

    def get_pin(self, pin):
        """Прочитать состояние пина."""
        idr = self._compute_idr()
        return bool(idr & (1 << pin))

    def _compute_idr(self):
        """
        Вычислить IDR на основе:
        - MODER: какие пины входы, какие выходы
        - ODR: значение выходных пинов (читаются обратно)
        - external_input: внешние сигналы на входных пинах
        """
        moder = self._regs.get(self.MODER, 0)
        odr = self._regs.get(self.ODR, 0)
        idr = 0

        for pin in range(16):
            mode = (moder >> (pin * 2)) & 0x3
            if mode == 0b00:
                # Input mode — читаем внешний вход
                if self._external_input & (1 << pin):
                    idr |= (1 << pin)
            elif mode == 0b01:
                # Output mode — IDR отражает ODR
                if odr & (1 << pin):
                    idr |= (1 << pin)
            elif mode == 0b10:
                # Alternate function — IDR отражает внешний вход
                if self._external_input & (1 << pin):
                    idr |= (1 << pin)
            else:
                # Analog — IDR = 0
                pass

        return idr

    # === Read ===

    def read32(self, address):
        off = self._offset(address)

        if off == self.IDR:
            val = self._compute_idr()
            if self.trace_enabled:
                print(f"[{self.name}] Read IDR -> 0x{val:04X}")
            return val

        if off == self.BSRR:
            return 0  # BSRR is write-only

        val = self._regs.get(off, 0)
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
        byte_pos = address & 3
        return (val32 >> (byte_pos * 8)) & 0xFF

    # === Write ===

    def write32(self, address, value):
        off = self._offset(address)
        value &= 0xFFFFFFFF

        if self.trace_enabled:
            name = self._reg_name(off)
            print(f"[{self.name}] Write {name} = 0x{value:08X}")

        if off == self.BSRR:
            self._handle_bsrr(value)
            return

        if off == self.IDR:
            return  # IDR is read-only

        self._regs[off] = value

        if off == self.ODR and self.on_output_change:
            self.on_output_change(self.name, value)

    def write16(self, address, value):
        aligned = address & ~3
        off = self._offset(aligned)
        old = self._regs.get(off, 0)
        if address & 2:
            new = (old & 0x0000FFFF) | ((value & 0xFFFF) << 16)
        else:
            new = (old & 0xFFFF0000) | (value & 0xFFFF)
        self.write32(aligned, new)

    def write8(self, address, value):
        aligned = address & ~3
        off = self._offset(aligned)
        old = self._regs.get(off, 0)
        byte_pos = address & 3
        mask = 0xFF << (byte_pos * 8)
        new = (old & ~mask) | ((value & 0xFF) << (byte_pos * 8))
        self.write32(aligned, new)

    # === BSRR logic ===

    def _handle_bsrr(self, value):
        """
        BSRR — Bit Set/Reset Register (write-only).
        Bits [15:0]: set corresponding ODR bits
        Bits [31:16]: reset corresponding ODR bits
        Reset has priority over set.
        """
        odr = self._regs.get(self.ODR, 0)

        set_bits = value & 0xFFFF
        reset_bits = (value >> 16) & 0xFFFF

        odr |= set_bits
        odr &= ~reset_bits

        self._regs[self.ODR] = odr & 0xFFFF

        if self.on_output_change:
            self.on_output_change(self.name, odr)

    def _reg_name(self, offset):
        names = {
            0x00: "MODER", 0x04: "OTYPER", 0x08: "OSPEEDR", 0x0C: "PUPDR",
            0x10: "IDR", 0x14: "ODR", 0x18: "BSRR", 0x1C: "LCKR",
            0x20: "AFRL", 0x24: "AFRH",
        }
        return names.get(offset, f"REG_0x{offset:03X}")

    def __repr__(self):
        odr = self._regs.get(self.ODR, 0)
        idr = self._compute_idr()
        return f"{self.name}(IDR=0x{idr:04X}, ODR=0x{odr:04X})"


class GPIO:
    """
    Контроллер всех GPIO портов.
    Создаёт GPIOA-GPIOE и предоставляет единый интерфейс.
    """

    # Default MODER values after reset (из Reference Manual)
    # GPIOA: PA13=AF(SWDIO), PA14=AF(SWCLK), PA15=AF(JTDI) → bits set
    # GPIOB: PB3=AF(SWO), PB4=AF(NJTRST) → bits set
    # Остальные порты: все пины в analog mode (0b11) или input (0b00)
    
    GPIOA_DEFAULT_MODER = 0xABFFFFFF  # PA13-15 = AF
    GPIOB_DEFAULT_MODER = 0xFFFFFEBF  # PB3-4 = AF  
    GPIOC_DEFAULT_MODER = 0x00000000
    GPIOD_DEFAULT_MODER = 0x00000000
    GPIOE_DEFAULT_MODER = 0x00000000

    def __init__(self):
        self.ports = {
            'A': GPIOPort("GPIOA", 0x58020000, self.GPIOA_DEFAULT_MODER),
            'B': GPIOPort("GPIOB", 0x58020400, self.GPIOB_DEFAULT_MODER),
            'C': GPIOPort("GPIOC", 0x58020800, self.GPIOC_DEFAULT_MODER),
            'D': GPIOPort("GPIOD", 0x58020C00, self.GPIOD_DEFAULT_MODER),
            'E': GPIOPort("GPIOE", 0x58021000, self.GPIOE_DEFAULT_MODER),
        }
        self._all_ports = list(self.ports.values())

    def find_port(self, address):
        """Найти порт по адресу."""
        for port in self._all_ports:
            if port.contains(address):
                return port
        return None

    def read32(self, address):
        port = self.find_port(address)
        if port:
            return port.read32(address)
        return 0

    def write32(self, address, value):
        port = self.find_port(address)
        if port:
            port.write32(address, value)

    def read16(self, address):
        port = self.find_port(address)
        if port:
            return port.read16(address)
        return 0

    def write16(self, address, value):
        port = self.find_port(address)
        if port:
            port.write16(address, value)

    def read8(self, address):
        port = self.find_port(address)
        if port:
            return port.read8(address)
        return 0

    def write8(self, address, value):
        port = self.find_port(address)
        if port:
            port.write8(address, value)

    def set_pin(self, port_name, pin, high):
        """Установить входной пин. port_name='A'..'E', pin=0..15."""
        port = self.ports.get(port_name.upper())
        if port:
            port.set_pin(pin, high)

    def get_pin(self, port_name, pin):
        """Прочитать пин."""
        port = self.ports.get(port_name.upper())
        if port:
            return port.get_pin(pin)
        return False

    def contains(self, address):
        return any(p.contains(address) for p in self._all_ports)

    def reset(self):
        for port in self._all_ports:
            port.reset()

    def __repr__(self):
        parts = [repr(p) for p in self._all_ports]
        return f"GPIO({', '.join(parts)})"

"""
ARM Cortex-M7 Register File

Регистры:
- R0-R12: General purpose
- R13 (SP): Stack Pointer (MSP и PSP)
- R14 (LR): Link Register
- R15 (PC): Program Counter
- xPSR: Program Status Register (APSR + IPSR + EPSR)
- Специальные: PRIMASK, FAULTMASK, BASEPRI, CONTROL
"""

import struct


class PSR:
    """Program Status Register (xPSR = APSR | IPSR | EPSR)"""

    # APSR флаги (биты 27-31)
    N_BIT = 31  # Negative
    Z_BIT = 30  # Zero
    C_BIT = 29  # Carry
    V_BIT = 28  # Overflow
    Q_BIT = 27  # Saturation

    # IPSR (биты 0-8) — номер текущего исключения
    IPSR_MASK = 0x1FF

    # EPSR (биты 10-15, 24-26)
    T_BIT = 24  # Thumb state (всегда 1 для Cortex-M)
    ICI_IT_MASK_LOW = 0x0000FC00   # биты 10-15
    ICI_IT_MASK_HIGH = 0x06000000  # биты 25-26

    def __init__(self):
        self._value = 0
        # Cortex-M всегда в Thumb mode
        self.set_t(True)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, val):
        self._value = val & 0xFFFFFFFF

    # === Флаги APSR ===

    def _get_bit(self, bit):
        return bool(self._value & (1 << bit))

    def _set_bit(self, bit, val):
        if val:
            self._value |= (1 << bit)
        else:
            self._value &= ~(1 << bit)

    @property
    def N(self):
        return self._get_bit(self.N_BIT)

    @N.setter
    def N(self, val):
        self._set_bit(self.N_BIT, val)

    @property
    def Z(self):
        return self._get_bit(self.Z_BIT)

    @Z.setter
    def Z(self, val):
        self._set_bit(self.Z_BIT, val)

    @property
    def C(self):
        return self._get_bit(self.C_BIT)

    @C.setter
    def C(self, val):
        self._set_bit(self.C_BIT, val)

    @property
    def V(self):
        return self._get_bit(self.V_BIT)

    @V.setter
    def V(self, val):
        self._set_bit(self.V_BIT, val)

    @property
    def Q(self):
        return self._get_bit(self.Q_BIT)

    @Q.setter
    def Q(self, val):
        self._set_bit(self.Q_BIT, val)

    @property
    def T(self):
        return self._get_bit(self.T_BIT)

    def set_t(self, val):
        self._set_bit(self.T_BIT, val)

    # === IPSR ===

    @property
    def exception_number(self):
        return self._value & self.IPSR_MASK

    @exception_number.setter
    def exception_number(self, val):
        self._value = (self._value & ~self.IPSR_MASK) | (val & self.IPSR_MASK)

    def update_flags_nz(self, result):
        """Обновить N и Z по 32-битному результату."""
        result &= 0xFFFFFFFF
        self.N = bool(result & 0x80000000)
        self.Z = (result == 0)

    def update_flags_nzcv(self, result, carry, overflow):
        """Обновить все арифметические флаги."""
        result &= 0xFFFFFFFF
        self.N = bool(result & 0x80000000)
        self.Z = (result == 0)
        self.C = carry
        self.V = overflow

    def __repr__(self):
        flags = ""
        flags += "N" if self.N else "n"
        flags += "Z" if self.Z else "z"
        flags += "C" if self.C else "c"
        flags += "V" if self.V else "v"
        flags += "Q" if self.Q else "q"
        flags += "T" if self.T else "t"
        return f"PSR({flags}, exc={self.exception_number}, raw=0x{self._value:08X})"


class Registers:
    """
    Полный набор регистров ARM Cortex-M7.
    """

    # Индексы
    SP = 13
    LR = 14
    PC = 15

    def __init__(self):
        # R0-R15
        self._regs = [0] * 16

        # Program Status Register
        self.psr = PSR()

        # Два стековых указателя
        self._msp = 0  # Main Stack Pointer
        self._psp = 0  # Process Stack Pointer

        # Специальные регистры
        self.primask = 0     # 1 бит — запрет всех прерываний (кроме NMI/HardFault)
        self.faultmask = 0   # 1 бит — запрет всех прерываний (кроме NMI)
        self.basepri = 0     # 8 бит — порог приоритета
        self.control = 0     # 2 бита: nPRIV (бит 0), SPSEL (бит 1)

        # EXC_RETURN значение (устанавливается при входе в исключение)
        self.exc_return = 0xFFFFFFFF

    def __getitem__(self, index):
        """Чтение регистра R0-R15."""
        if index == self.SP:
            return self.sp
        if index == self.PC:
            # PC читается как текущий адрес + 4 (pipeline)
            return self._regs[self.PC]
        return self._regs[index] & 0xFFFFFFFF

    def __setitem__(self, index, value):
        """Запись регистра R0-R15."""
        value = value & 0xFFFFFFFF
        if index == self.SP:
            self.sp = value
        elif index == self.PC:
            # Запись в PC — бит 0 определяет Thumb state,
            # адрес выравнивается (бит 0 очищается)
            self.psr.set_t(bool(value & 1))
            self._regs[self.PC] = value & 0xFFFFFFFE
        else:
            self._regs[index] = value

    @property
    def sp(self):
        """Текущий Stack Pointer (MSP или PSP в зависимости от CONTROL.SPSEL)."""
        if self.control & 0x2 and self.psr.exception_number == 0:
            # SPSEL=1 и не в обработчике → PSP
            return self._psp & 0xFFFFFFFF
        return self._msp & 0xFFFFFFFF

    @sp.setter
    def sp(self, value):
        value = value & 0xFFFFFFFF
        if self.control & 0x2 and self.psr.exception_number == 0:
            self._psp = value
        else:
            self._msp = value

    @property
    def msp(self):
        return self._msp & 0xFFFFFFFF

    @msp.setter
    def msp(self, value):
        self._msp = value & 0xFFFFFFFF

    @property
    def psp(self):
        return self._psp & 0xFFFFFFFF

    @psp.setter
    def psp(self, value):
        self._psp = value & 0xFFFFFFFF

    @property
    def pc(self):
        return self._regs[self.PC] & 0xFFFFFFFF

    @pc.setter
    def pc(self, value):
        self._regs[self.PC] = value & 0xFFFFFFFE

    @property
    def lr(self):
        return self._regs[self.LR] & 0xFFFFFFFF

    @lr.setter
    def lr(self, value):
        self._regs[self.LR] = value & 0xFFFFFFFF

    def branch(self, address):
        """Переход по адресу. Бит 0 → Thumb state."""
        self.psr.set_t(bool(address & 1))
        self._regs[self.PC] = address & 0xFFFFFFFE

    def branch_link(self, address):
        """BL: сохранить адрес возврата в LR, перейти."""
        self._regs[self.LR] = (self.pc + 1) & 0xFFFFFFFF  # +1 для Thumb bit
        self.branch(address)

    def reset(self, initial_sp, initial_pc):
        """
        Сброс процессора.
        initial_sp: значение из адреса 0x00000000 (начальный MSP)
        initial_pc: значение из адреса 0x00000004 (Reset vector)
        """
        for i in range(16):
            self._regs[i] = 0

        self._msp = initial_sp & 0xFFFFFFFC  # SP выравнен по 4
        self._psp = 0
        self._regs[self.SP] = self._msp

        self.psr = PSR()  # сброс, T=1

        self.primask = 0
        self.faultmask = 0
        self.basepri = 0
        self.control = 0

        # Переход на Reset vector
        self.branch(initial_pc)

    def dump(self):
        """Дамп всех регистров для отладки."""
        lines = []
        for i in range(0, 13, 4):
            parts = []
            for j in range(i, min(i + 4, 13)):
                parts.append(f"R{j:2d}=0x{self._regs[j]:08X}")
            lines.append("  ".join(parts))
        lines.append(f"  SP=0x{self.sp:08X}  LR=0x{self.lr:08X}  PC=0x{self.pc:08X}")
        lines.append(f"  MSP=0x{self._msp:08X}  PSP=0x{self._psp:08X}")
        lines.append(f"  {self.psr}")
        lines.append(f"  PRIMASK={self.primask} BASEPRI=0x{self.basepri:02X} "
                      f"FAULTMASK={self.faultmask} CONTROL=0x{self.control:02X}")
        return "\n".join(lines)

    def __repr__(self):
        return f"Registers(PC=0x{self.pc:08X}, SP=0x{self.sp:08X}, {self.psr})"
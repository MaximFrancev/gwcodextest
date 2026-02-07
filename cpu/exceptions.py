"""
ARM Cortex-M7 Exception / Interrupt handling.

Cortex-M7 имеет встроенный NVIC (Nested Vectored Interrupt Controller).
Исключения 1-15 — системные, 16+ — внешние прерывания (IRQ0, IRQ1, ...).

Vector Table по умолчанию в адресе 0x00000000 (можно переместить через VTOR).
Каждый вектор — 4 байта (адрес обработчика, бит 0 = Thumb).
"""

from enum import IntEnum


class ExceptionType(IntEnum):
    """Номера исключений Cortex-M."""
    RESET = 1
    NMI = 2
    HARDFAULT = 3
    MEMMANAGE = 4
    BUSFAULT = 5
    USAGEFAULT = 6
    # 7-10 зарезервированы
    SVCALL = 11
    DEBUGMON = 12
    # 13 зарезервирован
    PENDSV = 14
    SYSTICK = 15
    # 16+ = IRQ0, IRQ1, ...

    @staticmethod
    def irq_to_exception(irq_number):
        """IRQ номер (0, 1, 2, ...) → номер исключения (16, 17, 18, ...)"""
        return irq_number + 16

    @staticmethod
    def exception_to_irq(exc_number):
        """Номер исключения → IRQ номер."""
        return exc_number - 16


# Приоритеты по умолчанию (фиксированные для системных исключений)
FIXED_PRIORITIES = {
    ExceptionType.RESET: -3,      # Наивысший, фиксированный
    ExceptionType.NMI: -2,        # Фиксированный
    ExceptionType.HARDFAULT: -1,  # Фиксированный
}

# EXC_RETURN значения (записываются в LR при входе в исключение)
EXC_RETURN_HANDLER_MSP = 0xFFFFFFF1   # Возврат в Handler mode, использовать MSP
EXC_RETURN_THREAD_MSP = 0xFFFFFFF9    # Возврат в Thread mode, использовать MSP
EXC_RETURN_THREAD_PSP = 0xFFFFFFFD    # Возврат в Thread mode, использовать PSP

# Количество внешних прерываний (STM32H7B0 поддерживает до 150)
MAX_EXTERNAL_INTERRUPTS = 150
MAX_EXCEPTIONS = 16 + MAX_EXTERNAL_INTERRUPTS


class ExceptionState:
    """Состояние одного исключения."""

    def __init__(self, number):
        self.number = number
        self.enabled = False
        self.pending = False
        self.active = False
        self.priority = 0  # 0 = наивысший настраиваемый

        # Фиксированные приоритеты
        if number in FIXED_PRIORITIES:
            self.priority = FIXED_PRIORITIES[number]
            self.enabled = True  # Всегда включены

    def __repr__(self):
        flags = []
        if self.enabled:
            flags.append("EN")
        if self.pending:
            flags.append("PEND")
        if self.active:
            flags.append("ACT")
        return f"Exc({self.number}, pri={self.priority}, {'/'.join(flags)})"


class ExceptionManager:
    """
    Управление исключениями и прерываниями Cortex-M7.
    
    Работает совместно с CPU для:
    - Приёма запросов прерываний от периферии
    - Определения наиболее приоритетного ожидающего исключения
    - Выполнения входа/выхода из обработчика (stacking/unstacking)
    """

    # SCB регистры (System Control Block) — базовый адрес 0xE000ED00
    SCB_BASE = 0xE000ED00
    VTOR_OFFSET = 0x08       # 0xE000ED08 — Vector Table Offset Register
    AIRCR_OFFSET = 0x0C      # 0xE000ED0C — Application Interrupt and Reset Control
    SCR_OFFSET = 0x10        # 0xE000ED10 — System Control Register
    CCR_OFFSET = 0x14        # 0xE000ED14 — Configuration and Control
    SHPR1_OFFSET = 0x18      # 0xE000ED18 — System Handler Priority 1
    SHPR2_OFFSET = 0x1C      # 0xE000ED1C — System Handler Priority 2
    SHPR3_OFFSET = 0x20      # 0xE000ED20 — System Handler Priority 3
    SHCSR_OFFSET = 0x24      # 0xE000ED24 — System Handler Control and State
    CFSR_OFFSET = 0x28       # 0xE000ED28 — Configurable Fault Status
    HFSR_OFFSET = 0x2C       # 0xE000ED2C — HardFault Status
    ICSR_OFFSET = -0x04      # 0xE000ED04 — Interrupt Control and State (ниже SCB_BASE+8)
    ICSR_ADDR = 0xE000ED04

    # NVIC регистры — базовый адрес 0xE000E100
    NVIC_BASE = 0xE000E100
    NVIC_ISER_BASE = 0xE000E100   # Interrupt Set-Enable (0-4)
    NVIC_ICER_BASE = 0xE000E180   # Interrupt Clear-Enable (0-4)
    NVIC_ISPR_BASE = 0xE000E200   # Interrupt Set-Pending (0-4)
    NVIC_ICPR_BASE = 0xE000E280   # Interrupt Clear-Pending (0-4)
    NVIC_IABR_BASE = 0xE000E300   # Interrupt Active Bit (0-4)
    NVIC_IPR_BASE = 0xE000E400    # Interrupt Priority (0-59, по байтам)

    # SysTick регистры
    SYSTICK_BASE = 0xE000E010

    def __init__(self):
        # Все исключения
        self.exceptions = {}
        for i in range(1, MAX_EXCEPTIONS):
            self.exceptions[i] = ExceptionState(i)

        # MemManage, BusFault, UsageFault по умолчанию выключены
        # HardFault, NMI, Reset — всегда включены (сделано в ExceptionState.__init__)

        # VTOR — Vector Table Offset Register
        self.vtor = 0x00000000

        # SCB регистры
        self.aircr = 0xFA050000   # VECTKEY в верхних 16 бит (read)
        self.scr = 0
        self.ccr = 0x00000200     # STKALIGN=1 по умолчанию
        self.shcsr = 0
        self.cfsr = 0
        self.hfsr = 0

        # PRIGROUP: определяет разделение группового/подгруппового приоритета
        self.prigroup = 0

        # Стек активных исключений (для вложенных прерываний)
        self._active_stack = []

    def reset(self):
        """Сброс менеджера исключений."""
        for exc in self.exceptions.values():
            exc.pending = False
            exc.active = False
            if exc.number not in FIXED_PRIORITIES:
                exc.priority = 0
                exc.enabled = False
        self.vtor = 0x00000000
        self.aircr = 0xFA050000
        self.scr = 0
        self.ccr = 0x00000200
        self.shcsr = 0
        self.cfsr = 0
        self.hfsr = 0
        self.prigroup = 0
        self._active_stack = []

    # ===============================================================
    # Управление прерываниями
    # ===============================================================

    def set_pending(self, exc_number):
        """Установить флаг pending для исключения."""
        if exc_number in self.exceptions:
            self.exceptions[exc_number].pending = True

    def clear_pending(self, exc_number):
        """Снять флаг pending."""
        if exc_number in self.exceptions:
            self.exceptions[exc_number].pending = False

    def set_enabled(self, exc_number, enabled=True):
        """Включить/выключить внешнее прерывание."""
        if exc_number in self.exceptions:
            # Фиксированные нельзя отключить
            if exc_number not in FIXED_PRIORITIES:
                self.exceptions[exc_number].enabled = enabled

    def set_priority(self, exc_number, priority):
        """Установить приоритет (для настраиваемых исключений)."""
        if exc_number in self.exceptions and exc_number not in FIXED_PRIORITIES:
            # STM32H7 использует 4 бита приоритета (биты [7:4])
            self.exceptions[exc_number].priority = priority & 0xF0

    def get_priority(self, exc_number):
        """Получить приоритет исключения."""
        if exc_number in self.exceptions:
            return self.exceptions[exc_number].priority
        return 256  # Наименьший

    # ===============================================================
    # Определение следующего исключения для обработки
    # ===============================================================

    def get_execution_priority(self, regs):
        """
        Текущий приоритет исполнения (самый высокий из активных + PRIMASK/etc).
        """
        # Начинаем с наименьшего приоритета
        current = 256

        # Учитываем активные исключения
        for exc in self.exceptions.values():
            if exc.active and exc.priority < current:
                current = exc.priority

        # PRIMASK
        if regs.primask & 1:
            if current > 0:
                current = 0

        # FAULTMASK
        if regs.faultmask & 1:
            if current > -1:
                current = -1

        # BASEPRI
        if regs.basepri > 0:
            if current > regs.basepri:
                current = regs.basepri

        return current

    def get_pending_exception(self, regs):
        """
        Найти ожидающее исключение с наивысшим приоритетом,
        которое может вытеснить текущее исполнение.
        
        Возвращает номер исключения или None.
        """
        exec_priority = self.get_execution_priority(regs)
        best = None
        best_priority = exec_priority  # Должен быть строго выше (меньше числом)

        for exc in self.exceptions.values():
            if not exc.pending:
                continue
            if not exc.enabled:
                # Системные исключения (1-15) проверяем отдельно
                if exc.number >= 16:
                    continue
                # Некоторые системные нужна проверка через SHCSR
                if exc.number in (ExceptionType.MEMMANAGE, ExceptionType.BUSFAULT,
                                  ExceptionType.USAGEFAULT):
                    if not exc.enabled:
                        continue
            if exc.priority < best_priority:
                best_priority = exc.priority
                best = exc.number

        return best

    # ===============================================================
    # Вход в обработчик исключения (Exception Entry / Stacking)
    # ===============================================================

    def exception_entry(self, cpu, exc_number):
        """
        Выполнить вход в обработчик исключения:
        1. Сохранить контекст на стек (stacking)
        2. Загрузить вектор обработчика
        3. Обновить состояние
        
        cpu: объект CortexM7 с доступом к регистрам и памяти
        """
        regs = cpu.regs
        exc = self.exceptions[exc_number]

        # Определить какой стек использовать для stacking
        # Если мы в Thread mode и SPSEL=1 → используем PSP
        use_psp = (regs.psr.exception_number == 0 and (regs.control & 0x2))

        if use_psp:
            frame_sp = regs.psp
        else:
            frame_sp = regs.msp

        # Выравнивание стека по 8 байт (если STKALIGN=1 в CCR)
        force_align = bool(self.ccr & 0x200)
        frame_align = 0
        if force_align and (frame_sp & 0x4):
            frame_align = 1
            frame_sp -= 4

        # Push exception frame (8 слов = 32 байта):
        # [SP+0]  R0
        # [SP+4]  R1
        # [SP+8]  R2
        # [SP+12] R3
        # [SP+16] R12
        # [SP+20] LR
        # [SP+24] ReturnAddress (PC)
        # [SP+28] xPSR (с битом выравнивания)
        frame_sp -= 32

        xpsr = regs.psr.value
        if frame_align:
            xpsr |= (1 << 9)  # Бит 9 xPSR = stack was aligned

        return_addr = regs.pc

        cpu.mem_write32(frame_sp + 0, regs[0])
        cpu.mem_write32(frame_sp + 4, regs[1])
        cpu.mem_write32(frame_sp + 8, regs[2])
        cpu.mem_write32(frame_sp + 12, regs[3])
        cpu.mem_write32(frame_sp + 16, regs[12])
        cpu.mem_write32(frame_sp + 20, regs.lr)
        cpu.mem_write32(frame_sp + 24, return_addr)
        cpu.mem_write32(frame_sp + 28, xpsr)

        # Обновить стековый указатель
        if use_psp:
            regs.psp = frame_sp
        else:
            regs.msp = frame_sp

        # Установить EXC_RETURN в LR
        if regs.psr.exception_number != 0:
            # Из Handler mode → всегда MSP
            regs.lr = EXC_RETURN_HANDLER_MSP
        else:
            if use_psp:
                regs.lr = EXC_RETURN_THREAD_PSP
            else:
                regs.lr = EXC_RETURN_THREAD_MSP

        # Обновить состояние исключения
        exc.pending = False
        exc.active = True
        self._active_stack.append(exc_number)

        # Обновить IPSR
        regs.psr.exception_number = exc_number

        # Переключиться на MSP в Handler mode
        # (CONTROL.SPSEL игнорируется в Handler mode)

        # Загрузить вектор обработчика из vector table
        vector_addr = self.vtor + (exc_number * 4)
        handler = cpu.mem_read32(vector_addr)

        # Перейти на обработчик
        regs.branch(handler)

    # ===============================================================
    # Выход из обработчика (Exception Return / Unstacking)
    # ===============================================================

    def exception_return(self, cpu, exc_return_value):
        """
        Выполнить возврат из обработчика исключения.
        Вызывается когда PC загружается значением EXC_RETURN (0xFFFFFFFx).
        
        exc_return_value: значение EXC_RETURN из LR/PC
        """
        regs = cpu.regs

        # Определить откуда восстанавливать стек
        return_to_handler = (exc_return_value & 0xF) == 0x1
        use_psp = (exc_return_value & 0x4) != 0

        if use_psp:
            frame_sp = regs.psp
        else:
            frame_sp = regs.msp

        # Pop exception frame
        regs[0] = cpu.mem_read32(frame_sp + 0)
        regs[1] = cpu.mem_read32(frame_sp + 4)
        regs[2] = cpu.mem_read32(frame_sp + 8)
        regs[3] = cpu.mem_read32(frame_sp + 12)
        regs[12] = cpu.mem_read32(frame_sp + 16)
        regs.lr = cpu.mem_read32(frame_sp + 20)
        return_addr = cpu.mem_read32(frame_sp + 24)
        xpsr = cpu.mem_read32(frame_sp + 28)

        frame_sp += 32

        # Восстановить выравнивание
        if xpsr & (1 << 9):
            frame_sp += 4

        # Обновить стековый указатель
        if use_psp:
            regs.psp = frame_sp
        else:
            regs.msp = frame_sp

        # Деактивировать текущее исключение
        if self._active_stack:
            deactivated = self._active_stack.pop()
            if deactivated in self.exceptions:
                self.exceptions[deactivated].active = False

        # Восстановить xPSR (без бита 9)
        xpsr &= ~(1 << 9)
        regs.psr.value = xpsr

        # Обновить IPSR — предыдущее активное исключение
        if self._active_stack:
            regs.psr.exception_number = self._active_stack[-1]
        else:
            regs.psr.exception_number = 0  # Thread mode

        # Перейти на адрес возврата
        regs.branch(return_addr)

    @staticmethod
    def is_exc_return(value):
        """Проверить, является ли значение EXC_RETURN."""
        return (value & 0xFFFFFF00) == 0xFFFFFF00

    # ===============================================================
    # NVIC регистры — чтение/запись
    # ===============================================================

    def nvic_read(self, address):
        """Чтение NVIC/SCB регистров."""
        # ISER0-ISER4 (Interrupt Set-Enable)
        if self.NVIC_ISER_BASE <= address < self.NVIC_ISER_BASE + 20:
            reg_idx = (address - self.NVIC_ISER_BASE) // 4
            return self._read_enable_bits(reg_idx)

        # ICER0-ICER4
        if self.NVIC_ICER_BASE <= address < self.NVIC_ICER_BASE + 20:
            reg_idx = (address - self.NVIC_ICER_BASE) // 4
            return self._read_enable_bits(reg_idx)

        # ISPR0-ISPR4
        if self.NVIC_ISPR_BASE <= address < self.NVIC_ISPR_BASE + 20:
            reg_idx = (address - self.NVIC_ISPR_BASE) // 4
            return self._read_pending_bits(reg_idx)

        # ICPR0-ICPR4
        if self.NVIC_ICPR_BASE <= address < self.NVIC_ICPR_BASE + 20:
            reg_idx = (address - self.NVIC_ICPR_BASE) // 4
            return self._read_pending_bits(reg_idx)

        # IABR0-IABR4
        if self.NVIC_IABR_BASE <= address < self.NVIC_IABR_BASE + 20:
            reg_idx = (address - self.NVIC_IABR_BASE) // 4
            return self._read_active_bits(reg_idx)

        # IPR0-IPR59 (Interrupt Priority, побайтово упакованы по 4)
        if self.NVIC_IPR_BASE <= address < self.NVIC_IPR_BASE + 240:
            offset = address - self.NVIC_IPR_BASE
            irq_base = (offset // 4) * 4
            val = 0
            for i in range(4):
                irq = irq_base + i
                exc_num = irq + 16
                if exc_num in self.exceptions:
                    val |= (self.exceptions[exc_num].priority & 0xF0) << (i * 8)
            return val

        # ICSR
        if address == self.ICSR_ADDR:
            return self._read_icsr()

        # SCB регистры
        if address == self.SCB_BASE + self.VTOR_OFFSET:
            return self.vtor
        if address == self.SCB_BASE + self.AIRCR_OFFSET:
            return self.aircr
        if address == self.SCB_BASE + self.SCR_OFFSET:
            return self.scr
        if address == self.SCB_BASE + self.CCR_OFFSET:
            return self.ccr
        if address == self.SCB_BASE + self.SHCSR_OFFSET:
            return self.shcsr
        if address == self.SCB_BASE + self.CFSR_OFFSET:
            return self.cfsr
        if address == self.SCB_BASE + self.HFSR_OFFSET:
            return self.hfsr

        # SHPR1-3 (System Handler Priority)
        if address == self.SCB_BASE + self.SHPR1_OFFSET:
            return self._read_shpr(4)  # exc 4,5,6,7
        if address == self.SCB_BASE + self.SHPR2_OFFSET:
            return self._read_shpr(8)  # exc 8,9,10,11
        if address == self.SCB_BASE + self.SHPR3_OFFSET:
            return self._read_shpr(12) # exc 12,13,14,15

        # CPUID
        if address == self.SCB_BASE:
            return 0x411FC271  # Cortex-M7 r1p1

        return 0

    def nvic_write(self, address, value):
        """Запись NVIC/SCB регистров."""
        value &= 0xFFFFFFFF

        # ISER0-ISER4
        if self.NVIC_ISER_BASE <= address < self.NVIC_ISER_BASE + 20:
            reg_idx = (address - self.NVIC_ISER_BASE) // 4
            self._write_enable_bits(reg_idx, value, enable=True)
            return

        # ICER0-ICER4
        if self.NVIC_ICER_BASE <= address < self.NVIC_ICER_BASE + 20:
            reg_idx = (address - self.NVIC_ICER_BASE) // 4
            self._write_enable_bits(reg_idx, value, enable=False)
            return

        # ISPR0-ISPR4
        if self.NVIC_ISPR_BASE <= address < self.NVIC_ISPR_BASE + 20:
            reg_idx = (address - self.NVIC_ISPR_BASE) // 4
            self._write_pending_bits(reg_idx, value, pend=True)
            return

        # ICPR0-ICPR4
        if self.NVIC_ICPR_BASE <= address < self.NVIC_ICPR_BASE + 20:
            reg_idx = (address - self.NVIC_ICPR_BASE) // 4
            self._write_pending_bits(reg_idx, value, pend=False)
            return

        # IPR
        if self.NVIC_IPR_BASE <= address < self.NVIC_IPR_BASE + 240:
            offset = address - self.NVIC_IPR_BASE
            irq_base = (offset // 4) * 4
            for i in range(4):
                irq = irq_base + i
                exc_num = irq + 16
                pri = (value >> (i * 8)) & 0xFF
                self.set_priority(exc_num, pri)
            return

        # ICSR
        if address == self.ICSR_ADDR:
            self._write_icsr(value)
            return

        # SCB
        if address == self.SCB_BASE + self.VTOR_OFFSET:
            self.vtor = value & 0xFFFFFF80  # Биты [6:0] зарезервированы
            return
        if address == self.SCB_BASE + self.AIRCR_OFFSET:
            if (value >> 16) == 0x05FA:  # VECTKEY
                self.prigroup = (value >> 8) & 0x7
                if value & 0x4:  # SYSRESETREQ
                    pass  # TODO: системный сброс
            return
        if address == self.SCB_BASE + self.SCR_OFFSET:
            self.scr = value & 0x1E
            return
        if address == self.SCB_BASE + self.CCR_OFFSET:
            self.ccr = value
            return
        if address == self.SCB_BASE + self.SHCSR_OFFSET:
            self.shcsr = value
            # Обновить enabled для MemManage, BusFault, UsageFault
            self.exceptions[ExceptionType.MEMMANAGE].enabled = bool(value & (1 << 16))
            self.exceptions[ExceptionType.BUSFAULT].enabled = bool(value & (1 << 17))
            self.exceptions[ExceptionType.USAGEFAULT].enabled = bool(value & (1 << 18))
            return
        if address == self.SCB_BASE + self.CFSR_OFFSET:
            self.cfsr &= ~value  # Write-1-to-clear
            return
        if address == self.SCB_BASE + self.HFSR_OFFSET:
            self.hfsr &= ~value  # Write-1-to-clear
            return

        # SHPR1-3
        if address == self.SCB_BASE + self.SHPR1_OFFSET:
            self._write_shpr(4, value)
            return
        if address == self.SCB_BASE + self.SHPR2_OFFSET:
            self._write_shpr(8, value)
            return
        if address == self.SCB_BASE + self.SHPR3_OFFSET:
            self._write_shpr(12, value)
            return

    # ===============================================================
    # Внутренние методы для NVIC битовых регистров
    # ===============================================================

    def _read_enable_bits(self, reg_idx):
        """Читать 32 бита enable для IRQ (reg_idx*32 .. reg_idx*32+31)."""
        val = 0
        base_irq = reg_idx * 32
        for i in range(32):
            exc_num = base_irq + i + 16
            if exc_num in self.exceptions and self.exceptions[exc_num].enabled:
                val |= (1 << i)
        return val

    def _write_enable_bits(self, reg_idx, value, enable):
        """Установить/снять enable для IRQ."""
        base_irq = reg_idx * 32
        for i in range(32):
            if value & (1 << i):
                exc_num = base_irq + i + 16
                self.set_enabled(exc_num, enable)

    def _read_pending_bits(self, reg_idx):
        val = 0
        base_irq = reg_idx * 32
        for i in range(32):
            exc_num = base_irq + i + 16
            if exc_num in self.exceptions and self.exceptions[exc_num].pending:
                val |= (1 << i)
        return val

    def _write_pending_bits(self, reg_idx, value, pend):
        base_irq = reg_idx * 32
        for i in range(32):
            if value & (1 << i):
                exc_num = base_irq + i + 16
                if pend:
                    self.set_pending(exc_num)
                else:
                    self.clear_pending(exc_num)

    def _read_active_bits(self, reg_idx):
        val = 0
        base_irq = reg_idx * 32
        for i in range(32):
            exc_num = base_irq + i + 16
            if exc_num in self.exceptions and self.exceptions[exc_num].active:
                val |= (1 << i)
        return val

    def _read_icsr(self):
        """Interrupt Control and State Register."""
        val = 0
        # VECTACTIVE [8:0]
        if self._active_stack:
            val |= self._active_stack[-1] & 0x1FF
        # VECTPENDING [20:12]
        # Найти наиболее приоритетный pending (без учёта preemption)
        best_num = 0
        best_pri = 256
        for exc in self.exceptions.values():
            if exc.pending and exc.enabled and exc.priority < best_pri:
                best_pri = exc.priority
                best_num = exc.number
        val |= (best_num & 0x1FF) << 12
        # ISRPENDING [22]
        if best_num > 0:
            val |= (1 << 22)
        return val

    def _write_icsr(self, value):
        """Запись ICSR — позволяет программно установить/снять pending."""
        # PENDSTSET [26]
        if value & (1 << 26):
            self.set_pending(ExceptionType.SYSTICK)
        # PENDSTCLR [25]
        if value & (1 << 25):
            self.clear_pending(ExceptionType.SYSTICK)
        # PENDSVSET [28]
        if value & (1 << 28):
            self.set_pending(ExceptionType.PENDSV)
        # PENDSVCLR [27]
        if value & (1 << 27):
            self.clear_pending(ExceptionType.PENDSV)
        # NMIPENDSET [31]
        if value & (1 << 31):
            self.set_pending(ExceptionType.NMI)

    def _read_shpr(self, base_exc):
        """Читать System Handler Priority Register (4 приоритета)."""
        val = 0
        for i in range(4):
            exc_num = base_exc + i
            if exc_num in self.exceptions:
                val |= (self.exceptions[exc_num].priority & 0xFF) << (i * 8)
        return val

    def _write_shpr(self, base_exc, value):
        """Записать System Handler Priority Register."""
        for i in range(4):
            exc_num = base_exc + i
            pri = (value >> (i * 8)) & 0xFF
            self.set_priority(exc_num, pri)

    # ===============================================================
    # Проверка диапазона адресов
    # ===============================================================

    @staticmethod
    def handles_address(address):
        """Проверить, относится ли адрес к NVIC/SCB."""
        # SysTick: 0xE000E010-0xE000E0FF
        # NVIC:    0xE000E100-0xE000E4FF
        # SCB:     0xE000ED00-0xE000ED3F
        # ICSR:    0xE000ED04
        if 0xE000E100 <= address <= 0xE000E4FF:
            return True
        if 0xE000ED00 <= address <= 0xE000ED3F:
            return True
        if address == 0xE000ED04:
            return True
        return False
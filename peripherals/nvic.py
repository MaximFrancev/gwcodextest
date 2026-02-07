"""
NVIC — Nested Vectored Interrupt Controller (wrapper)

NVIC встроен в ядро Cortex-M7 и уже реализован в cpu/exceptions.py.
Этот модуль — тонкая обёртка для удобной регистрации в bus.

Адреса:
  0xE000E100 - 0xE000E4FF: NVIC registers
  0xE000ED00 - 0xE000ED3F: SCB registers
  0xE000ED04: ICSR

Все обращения проксируются в ExceptionManager.
"""


class NVIC:
    """
    NVIC wrapper для регистрации в SystemBus.
    
    Реальная логика в ExceptionManager (cpu/exceptions.py).
    Этот класс просто проксирует вызовы.
    """

    # Покрываем всё пространство NVIC + SCB
    NVIC_START = 0xE000E100
    NVIC_END   = 0xE000E4FF
    SCB_START  = 0xE000ED00
    SCB_END    = 0xE000ED3F
    ICSR_ADDR  = 0xE000ED04

    def __init__(self, exc_manager):
        """
        exc_manager: ExceptionManager из cpu/exceptions.py
        """
        self.exc_manager = exc_manager
        self.trace_enabled = False

    def contains(self, address):
        """Проверить, обрабатывает ли NVIC данный адрес."""
        if self.NVIC_START <= address <= self.NVIC_END:
            return True
        if self.SCB_START <= address <= self.SCB_END:
            return True
        if address == self.ICSR_ADDR:
            return True
        return False

    def read32(self, address):
        val = self.exc_manager.nvic_read(address)
        if self.trace_enabled:
            name = self._addr_name(address)
            print(f"[NVIC] Read {name} (0x{address:08X}) -> 0x{val:08X}")
        return val

    def write32(self, address, value):
        if self.trace_enabled:
            name = self._addr_name(address)
            print(f"[NVIC] Write {name} (0x{address:08X}) = 0x{value:08X}")
        self.exc_manager.nvic_write(address, value & 0xFFFFFFFF)

    def read8(self, address):
        val32 = self.read32(address & ~3)
        return (val32 >> ((address & 3) * 8)) & 0xFF

    def read16(self, address):
        val32 = self.read32(address & ~3)
        if address & 2:
            return (val32 >> 16) & 0xFFFF
        return val32 & 0xFFFF

    def write8(self, address, value):
        # Для NVIC IPR регистров побайтовая запись важна
        aligned = address & ~3
        old = self.read32(aligned)
        bp = address & 3
        mask = 0xFF << (bp * 8)
        new = (old & ~mask) | ((value & 0xFF) << (bp * 8))
        self.write32(aligned, new)

    def write16(self, address, value):
        aligned = address & ~3
        old = self.read32(aligned)
        if address & 2:
            new = (old & 0x0000FFFF) | ((value & 0xFFFF) << 16)
        else:
            new = (old & 0xFFFF0000) | (value & 0xFFFF)
        self.write32(aligned, new)

    # === IRQ convenience methods ===

    def enable_irq(self, irq_number):
        """Включить внешнее прерывание (IRQ 0-149)."""
        exc_num = irq_number + 16
        self.exc_manager.set_enabled(exc_num, True)

    def disable_irq(self, irq_number):
        """Выключить внешнее прерывание."""
        exc_num = irq_number + 16
        self.exc_manager.set_enabled(exc_num, False)

    def set_irq_pending(self, irq_number):
        """Установить pending для IRQ."""
        exc_num = irq_number + 16
        self.exc_manager.set_pending(exc_num)

    def clear_irq_pending(self, irq_number):
        """Снять pending для IRQ."""
        exc_num = irq_number + 16
        self.exc_manager.clear_pending(exc_num)

    def set_irq_priority(self, irq_number, priority):
        """Установить приоритет IRQ."""
        exc_num = irq_number + 16
        self.exc_manager.set_priority(exc_num, priority)

    # === STM32H7B0 specific IRQ numbers ===
    # Часто используемые в Game & Watch

    IRQ_LTDC     = 88
    IRQ_LTDC_ER  = 89
    IRQ_DMA1_S0  = 11
    IRQ_DMA1_S1  = 12
    IRQ_DMA2_S0  = 56
    IRQ_SPI2     = 36
    IRQ_SAI1     = 87
    IRQ_OCTOSPI1 = 92
    IRQ_TIM1_UP  = 25
    IRQ_TIM2     = 28
    IRQ_TIM3     = 29
    IRQ_EXTI0    = 6
    IRQ_EXTI1    = 7
    IRQ_EXTI2    = 8
    IRQ_EXTI3    = 9
    IRQ_EXTI4    = 10

    def _addr_name(self, address):
        """Имя регистра по адресу."""
        if 0xE000E100 <= address < 0xE000E120:
            idx = (address - 0xE000E100) // 4
            return f"ISER{idx}"
        if 0xE000E180 <= address < 0xE000E1A0:
            idx = (address - 0xE000E180) // 4
            return f"ICER{idx}"
        if 0xE000E200 <= address < 0xE000E220:
            idx = (address - 0xE000E200) // 4
            return f"ISPR{idx}"
        if 0xE000E280 <= address < 0xE000E2A0:
            idx = (address - 0xE000E280) // 4
            return f"ICPR{idx}"
        if 0xE000E300 <= address < 0xE000E320:
            idx = (address - 0xE000E300) // 4
            return f"IABR{idx}"
        if 0xE000E400 <= address < 0xE000E4F0:
            idx = (address - 0xE000E400) // 4
            return f"IPR{idx}"

        scb_names = {
            0xE000ED00: "CPUID",
            0xE000ED04: "ICSR",
            0xE000ED08: "VTOR",
            0xE000ED0C: "AIRCR",
            0xE000ED10: "SCR",
            0xE000ED14: "CCR",
            0xE000ED18: "SHPR1",
            0xE000ED1C: "SHPR2",
            0xE000ED20: "SHPR3",
            0xE000ED24: "SHCSR",
            0xE000ED28: "CFSR",
            0xE000ED2C: "HFSR",
        }
        return scb_names.get(address, f"0x{address:08X}")

    def __repr__(self):
        return "NVIC(wrapper)"

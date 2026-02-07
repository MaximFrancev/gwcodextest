"""
System Bus — маршрутизация адресов к памяти и периферии.

Центральный хаб: CPU вызывает bus.read32(addr)/bus.write32(addr, val),
а шина направляет запрос в нужный контроллер:
  - ITCM/DTCM/AXI/AHB SRAM
  - Internal Flash (+ alias на 0x00000000)
  - External Flash (OCTOSPI memory-mapped)
  - NVIC / SCB (System peripherals)
  - Peripheral stubs (GPIO, RCC, LTDC, etc.)
"""

from memory.sram import SRAMController
from memory.flash import FlashController
from memory.external_flash import ExternalFlash
from cpu.exceptions import ExceptionManager


class SystemBus:
    """
    STM32H7B0 System Bus.
    
    Маршрутизация адресов по карте памяти.
    Peripheral handlers регистрируются через register_peripheral().
    """

    def __init__(self):
        # Основные подсистемы памяти
        self.sram = SRAMController()
        self.flash = FlashController()
        self.ext_flash = ExternalFlash()

        # Exception manager (NVIC/SCB) — будет установлен при подключении CPU
        self.exc_manager = None

        # Зарегистрированные периферийные устройства
        # Список кортежей (start, end, peripheral)
        self._peripherals = []

        # Peripheral stub для неизвестных адресов
        self._stub_reads = {}   # addr -> last written value
        self._stub_enabled = True

        # Logging
        self.trace_enabled = False
        self._unhandled_reads = set()
        self._unhandled_writes = set()

        # Boot mode:
        # True = адрес 0x00000000 алиасит Flash Bank1 (для vector table при reset)
        # False = адрес 0x00000000 читает ITCM RAM (после загрузки ITCM firmware'ом)
        self._boot_from_flash = True

        # ITCM override data (загружается отдельно, применяется после reset)
        self._itcm_override_data = None

    # =============================================================
    # Peripheral registration
    # =============================================================

    def register_peripheral(self, start, end, peripheral):
        """
        Зарегистрировать периферийное устройство.
        
        peripheral должен реализовать:
          read32(address) -> int
          write32(address, value)
          (опционально read8/read16/write8/write16)
        """
        self._peripherals.append((start, end, peripheral))
        self._peripherals.sort(key=lambda x: x[0])

    def set_exc_manager(self, exc_manager):
        """Подключить ExceptionManager для обработки NVIC/SCB обращений."""
        self.exc_manager = exc_manager

    # =============================================================
    # Boot mode control
    # =============================================================

    def set_boot_from_flash(self, enabled):
        """
        Управление boot alias.
        True: 0x00000000 -> Flash Bank1 (при reset)
        False: 0x00000000 -> ITCM RAM (после инициализации)
        """
        self._boot_from_flash = enabled

    def apply_itcm_override(self):
        """
        Применить ITCM override данные (из itcm.bin).
        Вызывается ПОСЛЕ reset CPU, чтобы не испортить vector table.
        
        На реальном MCU firmware сама копирует код в ITCM при старте.
        itcm.bin — это snapshot ITCM после инициализации.
        """
        if self._itcm_override_data is not None:
            data = self._itcm_override_data
            # НЕ перезаписываем первые 512 байт (vector table area)
            # На реальном MCU vector table в Flash, ITCM используется для быстрого кода
            # Но itcm.bin может содержать код с offset 0 
            # Безопаснее: загрузить itcm.bin целиком, но при boot читать из Flash
            self.sram.load_itcm(data)
            # Переключить на ITCM после загрузки
            # (пока оставляем boot_from_flash = True, 
            #  firmware сама переключит через VTOR)
            print(f"[BUS] Applied ITCM override: {len(data)} bytes")

    # =============================================================
    # Поиск обработчика
    # =============================================================

    def _find_peripheral(self, address):
        """Найти зарегистрированное периферийное устройство по адресу."""
        for start, end, periph in self._peripherals:
            if start <= address <= end:
                return periph
        return None

    # =============================================================
    # READ
    # =============================================================

    def read8(self, address):
        address &= 0xFFFFFFFF
        val = self._do_read(address, 8)
        return val & 0xFF

    def read16(self, address):
        address &= 0xFFFFFFFE
        val = self._do_read(address, 16)
        return val & 0xFFFF

    def read32(self, address):
        address &= 0xFFFFFFFC
        val = self._do_read(address, 32)
        return val & 0xFFFFFFFF

    def _do_read(self, address, width):
        """Основная логика маршрутизации чтения."""

        # 1. ITCM / Flash alias region (0x00000000 - 0x0000FFFF)
        if address < 0x00010000:
            if self._boot_from_flash:
                # Boot mode: алиас Flash Bank1 для vector table
                flash_addr = 0x08000000 + address
                return self._read_region(self.flash, flash_addr, width)
            else:
                # Normal mode: ITCM RAM
                if self.sram.contains(address):
                    return self._read_region(self.sram, address, width)
                # Fallback на Flash
                flash_addr = 0x08000000 + address
                return self._read_region(self.flash, flash_addr, width)

        # 2. Internal Flash (0x08000000 - 0x0811FFFF)
        if 0x08000000 <= address < 0x08200000:
            if self.flash.contains(address):
                return self._read_region(self.flash, address, width)
            return 0

        # 3. DTCM (0x20000000 - 0x2001FFFF)
        if 0x20000000 <= address < 0x20020000:
            return self._read_region(self.sram, address, width)

        # 4. AXI SRAM (0x24000000 - 0x240FFFFF)
        if 0x24000000 <= address < 0x24100000:
            return self._read_region(self.sram, address, width)

        # 5. AHB SRAM1 (0x30000000 - 0x3001FFFF)
        if 0x30000000 <= address < 0x30020000:
            return self._read_region(self.sram, address, width)

        # 6. AHB SRAM2 (0x30020000 - 0x30027FFF)
        if 0x30020000 <= address < 0x30028000:
            return self._read_region(self.sram, address, width)

        # 7. Backup SRAM (0x38800000 - 0x38800FFF)
        if 0x38800000 <= address < 0x38801000:
            return self._read_region(self.sram, address, width)

        # 8. External Flash (0x90000000 - 0x900FFFFF)
        if 0x90000000 <= address < 0x90100000:
            if self.ext_flash.contains(address):
                return self._read_region(self.ext_flash, address, width)
            return 0xFF

        # 9. System peripherals: NVIC, SCB, SysTick (0xE000E000 - 0xE000EFFF)
        if 0xE000E000 <= address <= 0xE000EFFF:
            return self._read_system_periph(address, width)

        # 10. Зарегистрированные периферийные устройства
        periph = self._find_peripheral(address)
        if periph is not None:
            return self._read_region(periph, address, width)

        # 11. Peripheral address space — stub
        if self._is_peripheral_addr(address):
            return self._stub_read(address, width)

        # Unknown
        if self.trace_enabled and address not in self._unhandled_reads:
            self._unhandled_reads.add(address)
            print(f"[BUS] Unhandled read{width} @ 0x{address:08X}")
        return 0

    # =============================================================
    # WRITE
    # =============================================================

    def write8(self, address, value):
        address &= 0xFFFFFFFF
        value &= 0xFF
        self._do_write(address, value, 8)

    def write16(self, address, value):
        address &= 0xFFFFFFFE
        value &= 0xFFFF
        self._do_write(address, value, 16)

    def write32(self, address, value):
        address &= 0xFFFFFFFC
        value &= 0xFFFFFFFF
        self._do_write(address, value, 32)

    def _do_write(self, address, value, width):
        """Основная логика маршрутизации записи."""

        # 1. ITCM (0x00000000 - 0x0000FFFF) — writable RAM
        if address < 0x00010000:
            if self.sram.contains(address):
                self._write_region(self.sram, address, value, width)
            # Запись в ITCM region также переключает на ITCM mode
            # (firmware записала что-то в ITCM → значит инициализировала)
            return

        # 2. Internal Flash — read only (запись игнорируется)
        if 0x08000000 <= address < 0x08200000:
            return

        # 3. DTCM
        if 0x20000000 <= address < 0x20020000:
            self._write_region(self.sram, address, value, width)
            return

        # 4. AXI SRAM
        if 0x24000000 <= address < 0x24100000:
            self._write_region(self.sram, address, value, width)
            return

        # 5. AHB SRAM1
        if 0x30000000 <= address < 0x30020000:
            self._write_region(self.sram, address, value, width)
            return

        # 6. AHB SRAM2
        if 0x30020000 <= address < 0x30028000:
            self._write_region(self.sram, address, value, width)
            return

        # 7. Backup SRAM
        if 0x38800000 <= address < 0x38801000:
            self._write_region(self.sram, address, value, width)
            return

        # 8. External Flash — read only
        if 0x90000000 <= address < 0x90100000:
            return

        # 9. System peripherals: NVIC, SCB, SysTick
        if 0xE000E000 <= address <= 0xE000EFFF:
            self._write_system_periph(address, value, width)
            return

        # 10. Зарегистрированные периферийные устройства
        periph = self._find_peripheral(address)
        if periph is not None:
            self._write_region(periph, address, value, width)
            return

        # 11. Peripheral stub
        if self._is_peripheral_addr(address):
            self._stub_write(address, value, width)
            return

        # Unknown
        if self.trace_enabled and address not in self._unhandled_writes:
            self._unhandled_writes.add(address)
            print(f"[BUS] Unhandled write{width} @ 0x{address:08X} = 0x{value:08X}")

    # =============================================================
    # Helpers для чтения/записи разной ширины
    # =============================================================

    def _read_region(self, region, address, width):
        if width == 8:
            return region.read8(address)
        elif width == 16:
            return region.read16(address)
        else:
            return region.read32(address)

    def _write_region(self, region, address, value, width):
        if width == 8:
            region.write8(address, value)
        elif width == 16:
            region.write16(address, value)
        else:
            region.write32(address, value)

    # =============================================================
    # System peripherals (NVIC / SCB / SysTick)
    # =============================================================

    def _read_system_periph(self, address, width):
        """Чтение из системных периферийных регистров."""
        if 0xE000E010 <= address <= 0xE000E01F:
            return self._read_systick(address)

        if self.exc_manager is not None:
            if ExceptionManager.handles_address(address):
                return self.exc_manager.nvic_read(address)

        if 0xE000EF30 <= address <= 0xE000EF44:
            return self._read_fpu(address)

        if 0xE000ED90 <= address <= 0xE000EDB8:
            return self._read_mpu(address)

        if 0xE000ED88 <= address <= 0xE000ED8C:
            return self._read_fpu(address)

        if 0xE000EDF0 <= address <= 0xE000EDFC:
            return 0

        return 0

    def _write_system_periph(self, address, value, width):
        """Запись в системные периферийные регистры."""
        if 0xE000E010 <= address <= 0xE000E01F:
            self._write_systick(address, value)
            return

        if self.exc_manager is not None:
            if ExceptionManager.handles_address(address):
                self.exc_manager.nvic_write(address, value)
                return

        if 0xE000EF30 <= address <= 0xE000EF44:
            self._write_fpu(address, value)
            return

        if 0xE000ED88 <= address <= 0xE000ED8C:
            self._write_fpu(address, value)
            return

        if 0xE000ED90 <= address <= 0xE000EDB8:
            self._write_mpu(address, value)
            return

    # =============================================================
    # SysTick
    # =============================================================

    _systick_ctrl = 0
    _systick_load = 0
    _systick_val = 0
    _systick_calib = 0x00000000

    def _read_systick(self, address):
        if address == 0xE000E010:
            return self._systick_ctrl
        elif address == 0xE000E014:
            return self._systick_load
        elif address == 0xE000E018:
            val = self._systick_val
            self._systick_ctrl &= ~(1 << 16)
            return val
        elif address == 0xE000E01C:
            return self._systick_calib
        return 0

    def _write_systick(self, address, value):
        if address == 0xE000E010:
            self._systick_ctrl = value & 0x00010007
        elif address == 0xE000E014:
            self._systick_load = value & 0x00FFFFFF
        elif address == 0xE000E018:
            self._systick_val = 0
            self._systick_ctrl &= ~(1 << 16)

    def tick_systick(self):
        """
        Вызывается каждый цикл CPU для обновления SysTick.
        Возвращает True если SysTick сгенерировал прерывание.
        """
        if not (self._systick_ctrl & 1):
            return False

        if self._systick_val > 0:
            self._systick_val -= 1
        else:
            self._systick_val = self._systick_load
            self._systick_ctrl |= (1 << 16)

            if self._systick_ctrl & (1 << 1):
                if self.exc_manager:
                    from cpu.exceptions import ExceptionType
                    self.exc_manager.set_pending(ExceptionType.SYSTICK)
                return True

        return False

    # =============================================================
    # FPU stub
    # =============================================================

    _fpu_cpacr = 0
    _fpu_fpccr = 0xC0000000
    _fpu_fpcar = 0
    _fpu_fpdscr = 0

    def _read_fpu(self, address):
        if address == 0xE000ED88:
            return self._fpu_cpacr
        elif address == 0xE000EF34:
            return self._fpu_fpccr
        elif address == 0xE000EF38:
            return self._fpu_fpcar
        elif address == 0xE000EF3C:
            return self._fpu_fpdscr
        return 0

    def _write_fpu(self, address, value):
        if address == 0xE000ED88:
            self._fpu_cpacr = value
        elif address == 0xE000EF34:
            self._fpu_fpccr = value
        elif address == 0xE000EF38:
            self._fpu_fpcar = value
        elif address == 0xE000EF3C:
            self._fpu_fpdscr = value

    # =============================================================
    # MPU stub
    # =============================================================

    _mpu_regs = {}

    def _read_mpu(self, address):
        if address == 0xE000ED90:
            return 0x00000800
        elif address == 0xE000ED94:
            return self._mpu_regs.get(0xE000ED94, 0)
        return self._mpu_regs.get(address, 0)

    def _write_mpu(self, address, value):
        self._mpu_regs[address] = value

    # =============================================================
    # Peripheral address detection
    # =============================================================

    @staticmethod
    def _is_peripheral_addr(address):
        if 0x40000000 <= address < 0x40008000:
            return True
        if 0x40010000 <= address < 0x40017000:
            return True
        if 0x40020000 <= address < 0x40080000:
            return True
        if 0x48020000 <= address < 0x48023000:
            return True
        if 0x51000000 <= address < 0x52009000:
            return True
        if 0x50000000 <= address < 0x50004000:
            return True
        if 0x58000000 <= address < 0x58027000:
            return True
        if 0x5C000000 <= address < 0x5C010000:
            return True
        return False

    # =============================================================
    # Peripheral stub
    # =============================================================

    def _stub_read(self, address, width):
        val = self._stub_reads.get(address, 0)
        if self.trace_enabled and address not in self._unhandled_reads:
            self._unhandled_reads.add(address)
            name = self._guess_peripheral_name(address)
            print(f"[BUS] Stub read{width} @ 0x{address:08X} ({name}) -> 0x{val:08X}")
        return val

    def _stub_write(self, address, value, width):
        self._stub_reads[address] = value
        if self.trace_enabled and address not in self._unhandled_writes:
            self._unhandled_writes.add(address)
            name = self._guess_peripheral_name(address)
            print(f"[BUS] Stub write{width} @ 0x{address:08X} ({name}) = 0x{value:08X}")

    @staticmethod
    def _guess_peripheral_name(address):
        known = [
            (0x58024400, 0x580247FF, "RCC"),
            (0x58020000, 0x580203FF, "GPIOA"),
            (0x58020400, 0x580207FF, "GPIOB"),
            (0x58020800, 0x58020BFF, "GPIOC"),
            (0x58020C00, 0x58020FFF, "GPIOD"),
            (0x58021000, 0x580213FF, "GPIOE"),
            (0x50001000, 0x50001FFF, "LTDC"),
            (0x40003800, 0x40003BFF, "SPI2"),
            (0x40015800, 0x40015BFF, "SAI1"),
            (0x52005000, 0x520053FF, "OCTOSPI1"),
            (0x52009000, 0x520093FF, "OCTOSPIM"),
            (0x52002000, 0x520023FF, "FLASH_IF"),
            (0x40020000, 0x400203FF, "DMA1"),
            (0x40020400, 0x400207FF, "DMA2"),
            (0x58025400, 0x580257FF, "BDMA"),
            (0x58024800, 0x58024BFF, "PWR"),
            (0x58000400, 0x580007FF, "SYSCFG"),
            (0x58000000, 0x580003FF, "EXTI"),
            (0x40005400, 0x400057FF, "I2C1"),
            (0x58004800, 0x58004BFF, "IWDG"),
            (0x40010000, 0x400103FF, "TIM1"),
            (0x40000000, 0x400003FF, "TIM2"),
            (0x40000400, 0x400007FF, "TIM3"),
            (0x5C001000, 0x5C0013FF, "DBGMCU"),
        ]
        for start, end, name in known:
            if start <= address <= end:
                return name
        return "UNKNOWN_PERIPH"

    # =============================================================
    # Загрузка ROM / инициализация
    # =============================================================

    def load_rom(self, internal_flash_path=None, external_flash_path=None,
                 itcm_path=None, key_info_path=None):
        """
        Загрузить все ROM файлы.
        """
        loaded = {}

        # 1. Internal Flash
        if internal_flash_path:
            import os
            if os.path.exists(internal_flash_path):
                size = self.flash.load_internal_flash(internal_flash_path)
                loaded['internal_flash'] = size
                print(f"[BUS] Loaded internal flash: {size} bytes")

                # Скопировать Flash Bank1 в ITCM (boot alias)
                # Это обеспечивает что vector table доступна через Flash alias
                boot_data = self.flash.get_boot_data_for_itcm()
                itcm_size = min(len(boot_data), 64 * 1024)
                self.sram.load_itcm(boot_data[:itcm_size])
                print(f"[BUS] Flash Bank1 -> ITCM alias: {itcm_size} bytes")

        # 2. ITCM override — СОХРАНЯЕМ, но НЕ применяем сейчас
        # Будет применено после reset через apply_itcm_override()
        if itcm_path:
            import os
            if os.path.exists(itcm_path):
                with open(itcm_path, 'rb') as f:
                    itcm_data = f.read()
                self._itcm_override_data = itcm_data
                loaded['itcm'] = len(itcm_data)
                print(f"[BUS] Loaded ITCM override: {len(itcm_data)} bytes (deferred)")

        # 3. External Flash
        if external_flash_path:
            import os
            if os.path.exists(external_flash_path):
                basename = os.path.basename(external_flash_path).lower()
                if 'decrypted' in basename:
                    size = self.ext_flash.load_decrypted(external_flash_path)
                else:
                    size = self.ext_flash.load_encrypted(external_flash_path)
                loaded['external_flash'] = size
                print(f"[BUS] Loaded external flash: {size} bytes"
                      f" ({'decrypted' if self.ext_flash.is_decrypted() else 'encrypted'})")

        # 4. Keys
        if key_info_path:
            import os
            if os.path.exists(key_info_path):
                if self.ext_flash.load_keys(key_info_path):
                    loaded['keys'] = True
                    print(f"[BUS] Loaded encryption keys")

        # Ensure boot from flash mode
        self._boot_from_flash = True

        return loaded

    def get_info(self):
        lines = ["=== System Bus ==="]
        lines.append(f"  SRAM: {self.sram}")
        lines.append(f"  Flash: {self.flash}")
        lines.append(f"  ExtFlash: {self.ext_flash}")
        lines.append(f"  Boot from Flash: {self._boot_from_flash}")
        lines.append(f"  Peripherals registered: {len(self._peripherals)}")
        lines.append(f"  Stub entries: {len(self._stub_reads)}")

        sp = self.read32(0x00000000)
        pc = self.read32(0x00000004)
        lines.append(f"  Vector[0] (SP):  0x{sp:08X}")
        lines.append(f"  Vector[1] (PC):  0x{pc:08X}")

        return '\n'.join(lines)

    def __repr__(self):
        return f"SystemBus(periphs={len(self._peripherals)}, stubs={len(self._stub_reads)})"

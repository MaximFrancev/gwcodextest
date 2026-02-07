"""
STM32H7B0VBT6 Memory Map

Определения всех регионов памяти для Game & Watch.
"""


class MemoryRegion:
    """Описание региона памяти."""

    def __init__(self, name, start, size, readable=True, writable=True, executable=True):
        self.name = name
        self.start = start
        self.size = size
        self.end = start + size - 1
        self.readable = readable
        self.writable = writable
        self.executable = executable

    def contains(self, address):
        return self.start <= address <= self.end

    def offset(self, address):
        return address - self.start

    def __repr__(self):
        flags = ""
        flags += "R" if self.readable else "-"
        flags += "W" if self.writable else "-"
        flags += "X" if self.executable else "-"
        return (f"MemRegion({self.name}: 0x{self.start:08X}-0x{self.end:08X}, "
                f"{self.size // 1024}KB, {flags})")


# ============================================================
# STM32H7B0 Memory Regions
# ============================================================

# ITCM RAM: 64KB at 0x00000000 (also mirrored)
ITCM_RAM = MemoryRegion("ITCM_RAM", 0x00000000, 64 * 1024)

# DTCM RAM: 128KB at 0x20000000
DTCM_RAM = MemoryRegion("DTCM_RAM", 0x20000000, 128 * 1024)

# AXI SRAM: 1MB at 0x24000000 (основная SRAM)
AXI_SRAM = MemoryRegion("AXI_SRAM", 0x24000000, 1024 * 1024)

# AHB SRAM1: 128KB at 0x30000000
AHB_SRAM1 = MemoryRegion("AHB_SRAM1", 0x30000000, 128 * 1024)

# AHB SRAM2: 32KB at 0x30020000
AHB_SRAM2 = MemoryRegion("AHB_SRAM2", 0x30020000, 32 * 1024)

# Backup SRAM: 4KB at 0x38800000
BACKUP_SRAM = MemoryRegion("BACKUP_SRAM", 0x38800000, 4 * 1024)

# Internal Flash Bank 1: 128KB at 0x08000000
INTERNAL_FLASH_BANK1 = MemoryRegion(
    "INTERNAL_FLASH_B1", 0x08000000, 128 * 1024,
    readable=True, writable=False, executable=True
)

# Internal Flash Bank 2: 128KB at 0x08100000
# (Undocumented, discovered by modding community)
INTERNAL_FLASH_BANK2 = MemoryRegion(
    "INTERNAL_FLASH_B2", 0x08100000, 128 * 1024,
    readable=True, writable=False, executable=True
)

# External Flash (OCTOSPI memory-mapped): 1MB at 0x90000000
EXTERNAL_FLASH = MemoryRegion(
    "EXTERNAL_FLASH", 0x90000000, 1024 * 1024,
    readable=True, writable=False, executable=True
)

# System Memory (boot ROM): 128KB at 0x1FF00000
SYSTEM_MEMORY = MemoryRegion(
    "SYSTEM_MEM", 0x1FF00000, 128 * 1024,
    readable=True, writable=False, executable=True
)

# ============================================================
# Peripheral regions
# ============================================================

# APB1 peripherals: 0x40000000 - 0x40007FFF
APB1_PERIPH = MemoryRegion(
    "APB1", 0x40000000, 0x8000,
    readable=True, writable=True, executable=False
)

# APB2 peripherals: 0x40010000 - 0x40016BFF
APB2_PERIPH = MemoryRegion(
    "APB2", 0x40010000, 0x6C00,
    readable=True, writable=True, executable=False
)

# AHB1 peripherals: 0x40020000 - 0x4007FFFF
AHB1_PERIPH = MemoryRegion(
    "AHB1", 0x40020000, 0x60000,
    readable=True, writable=True, executable=False
)

# AHB2 peripherals: 0x48020000 - 0x48022BFF (includes OCTOSPI regs)
AHB2_PERIPH = MemoryRegion(
    "AHB2", 0x48020000, 0x3000,
    readable=True, writable=True, executable=False
)

# AHB3 peripherals: 0x51000000 - 0x52008FFF
AHB3_PERIPH = MemoryRegion(
    "AHB3", 0x51000000, 0x1009000,
    readable=True, writable=True, executable=False
)

# APB3 peripherals: 0x50000000 - 0x50003FFF (LTDC, etc.)
APB3_PERIPH = MemoryRegion(
    "APB3", 0x50000000, 0x4000,
    readable=True, writable=True, executable=False
)

# AHB4 / APB4 peripherals: 0x58000000 - 0x580267FF
AHB4_PERIPH = MemoryRegion(
    "AHB4", 0x58000000, 0x27000,
    readable=True, writable=True, executable=False
)

# System peripherals (PPB): 0xE0000000 - 0xE00FFFFF
# Includes SysTick, NVIC, SCB, MPU, FPU, Debug
SYSTEM_PPB = MemoryRegion(
    "SYSTEM_PPB", 0xE0000000, 0x100000,
    readable=True, writable=True, executable=False
)

# ============================================================
# Specific peripheral base addresses
# ============================================================

# RCC (Reset and Clock Control)
RCC_BASE = 0x58024400

# GPIO ports
GPIOA_BASE = 0x58020000
GPIOB_BASE = 0x58020400
GPIOC_BASE = 0x58020800
GPIOD_BASE = 0x58020C00
GPIOE_BASE = 0x58021000

# LTDC (LCD-TFT Display Controller)
LTDC_BASE = 0x50001000

# SPI2 / I2S2
SPI2_BASE = 0x40003800

# SAI1 (Serial Audio Interface)
SAI1_BASE = 0x40015800

# OCTOSPI1
OCTOSPI1_BASE = 0x52005000
# OCTOSPI IO Manager
OCTOSPIM_BASE = 0x52009000

# DMA
DMA1_BASE = 0x40020000
DMA2_BASE = 0x40020400
BDMA_BASE = 0x58025400

# Timers
TIM1_BASE = 0x40010000
TIM2_BASE = 0x40000000
TIM3_BASE = 0x40000400

# PWR (Power Control)
PWR_BASE = 0x58024800

# SYSCFG
SYSCFG_BASE = 0x58000400

# EXTI
EXTI_BASE = 0x58000000

# Flash interface
FLASH_INTF_BASE = 0x52002000

# I2C1
I2C1_BASE = 0x40005400

# IWDG (Independent Watchdog)
IWDG_BASE = 0x58004800

# SysTick
SYSTICK_BASE = 0xE000E010

# NVIC
NVIC_BASE = 0xE000E100

# SCB (System Control Block)
SCB_BASE = 0xE000ED00

# FPU
FPU_BASE = 0xE000EF30

# MPU
MPU_BASE = 0xE000ED90

# DBGMCU
DBGMCU_BASE = 0x5C001000

# ============================================================
# All RAM regions list
# ============================================================

ALL_RAM_REGIONS = [
    ITCM_RAM,
    DTCM_RAM,
    AXI_SRAM,
    AHB_SRAM1,
    AHB_SRAM2,
    BACKUP_SRAM,
]

ALL_FLASH_REGIONS = [
    INTERNAL_FLASH_BANK1,
    INTERNAL_FLASH_BANK2,
    EXTERNAL_FLASH,
]

ALL_PERIPH_REGIONS = [
    APB1_PERIPH,
    APB2_PERIPH,
    AHB1_PERIPH,
    AHB2_PERIPH,
    AHB3_PERIPH,
    APB3_PERIPH,
    AHB4_PERIPH,
    SYSTEM_PPB,
]
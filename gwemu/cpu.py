from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .memory import MemoryMap, MemoryRegion


FLASH_BASE = 0x08000000
SRAM_BASE = 0x20000000


@dataclass
class CortexMEmulator:
    memory: MemoryMap
    regs: List[int] = field(default_factory=lambda: [0] * 16)
    xpsr: int = 0
    halted: bool = False

    def reset(self, vector_base: int = FLASH_BASE) -> None:
        self.regs[13] = self.memory.read32(vector_base)
        self.regs[15] = self.memory.read32(vector_base + 4) & ~1
        self.halted = False

    @property
    def pc(self) -> int:
        return self.regs[15]

    @pc.setter
    def pc(self, value: int) -> None:
        self.regs[15] = value & 0xFFFFFFFF

    def step(self) -> None:
        if self.halted:
            return
        instr = self.memory.read16(self.pc)
        next_pc = (self.pc + 2) & 0xFFFFFFFF
        self.pc = next_pc
        self._execute_thumb(instr, next_pc)

    def _execute_thumb(self, instr: int, next_pc: int) -> None:
        if instr == 0xBF00:
            return
        if instr == 0xBE00:
            self.halted = True
            return
        if instr & 0xF800 == 0x2000:
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            self.regs[rd] = imm8
            return
        if instr & 0xF800 == 0x3000:
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            self.regs[rd] = (self.regs[rd] + imm8) & 0xFFFFFFFF
            return
        if instr & 0xF800 == 0x3800:
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            self.regs[rd] = (self.regs[rd] - imm8) & 0xFFFFFFFF
            return
        if instr & 0xF800 == 0x4800:
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            pc_aligned = (next_pc + 2) & ~3
            address = (pc_aligned + (imm8 << 2)) & 0xFFFFFFFF
            self.regs[rd] = self.memory.read32(address)
            return
        if instr & 0xF800 == 0xE000:
            imm11 = instr & 0x7FF
            offset = self._sign_extend(imm11 << 1, 12)
            self.pc = (next_pc + offset) & 0xFFFFFFFF
            return
        if instr & 0xFF87 == 0x4700:
            rm = (instr >> 3) & 0xF
            target = self.regs[rm]
            self.pc = target & ~1
            return
        raise NotImplementedError(f"Unsupported instruction 0x{instr:04X} at 0x{next_pc - 2:08X}")

    @staticmethod
    def _sign_extend(value: int, bits: int) -> int:
        sign_bit = 1 << (bits - 1)
        return (value ^ sign_bit) - sign_bit


def build_default_memory(rom_data: bytes) -> MemoryMap:
    memory = MemoryMap()
    flash_size = max(len(rom_data), 256 * 1024)
    flash = MemoryRegion(
        base=FLASH_BASE,
        size=flash_size,
        data=bytearray(flash_size),
        read_only=False,
    )
    flash.write(FLASH_BASE, rom_data)
    flash.read_only = True
    memory.add_region(flash)

    sram = MemoryRegion(
        base=SRAM_BASE,
        size=256 * 1024,
        data=bytearray(256 * 1024),
    )
    memory.add_region(sram)
    return memory

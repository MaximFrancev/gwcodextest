from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .memory import MemoryMap, MemoryRegion


FLASH_BASE = 0x08000000
EXTERNAL_FLASH_BASE = 0x90000000
ITCM_BASE = 0x00000000
SRAM_BASE = 0x20000000


FLAG_NEGATIVE = 1 << 31
FLAG_ZERO = 1 << 30
FLAG_CARRY = 1 << 29
FLAG_OVERFLOW = 1 << 28


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
        if instr & 0xE000 == 0x0000:
            imm5 = (instr >> 6) & 0x1F
            rm = (instr >> 3) & 0x7
            rd = instr & 0x7
            if instr & 0x1800 == 0x0000:
                self.regs[rd] = (self.regs[rm] << imm5) & 0xFFFFFFFF
                self._set_flags_nz(self.regs[rd])
                return
            if instr & 0x1800 == 0x0800:
                shift = imm5 or 32
                self.regs[rd] = (self.regs[rm] >> shift) & 0xFFFFFFFF
                self._set_flags_nz(self.regs[rd])
                return
            if instr & 0x1800 == 0x1000:
                shift = imm5 or 32
                value = self.regs[rm]
                if value & 0x80000000:
                    self.regs[rd] = ((value >> shift) | (0xFFFFFFFF << (32 - shift))) & 0xFFFFFFFF
                else:
                    self.regs[rd] = (value >> shift) & 0xFFFFFFFF
                self._set_flags_nz(self.regs[rd])
                return
        if instr & 0xF800 == 0x2000:
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            self.regs[rd] = imm8
            self._set_flags_nz(self.regs[rd])
            return
        if instr & 0xF800 == 0x3000:
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            result = self.regs[rd] + imm8
            self._set_flags_add(self.regs[rd], imm8, result)
            self.regs[rd] = result & 0xFFFFFFFF
            return
        if instr & 0xF800 == 0x3800:
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            result = self.regs[rd] - imm8
            self._set_flags_sub(self.regs[rd], imm8, result)
            self.regs[rd] = result & 0xFFFFFFFF
            return
        if instr & 0xFFC0 == 0x1C00:
            rd = instr & 0x7
            rn = (instr >> 3) & 0x7
            rm = (instr >> 6) & 0x7
            result = self.regs[rn] + self.regs[rm]
            self._set_flags_add(self.regs[rn], self.regs[rm], result)
            self.regs[rd] = result & 0xFFFFFFFF
            return
        if instr & 0xFFC0 == 0x1E00:
            rd = instr & 0x7
            rn = (instr >> 3) & 0x7
            rm = (instr >> 6) & 0x7
            result = self.regs[rn] - self.regs[rm]
            self._set_flags_sub(self.regs[rn], self.regs[rm], result)
            self.regs[rd] = result & 0xFFFFFFFF
            return
        if instr & 0xF800 == 0x1800:
            rd = instr & 0x7
            rn = (instr >> 3) & 0x7
            rm = (instr >> 6) & 0x7
            result = self.regs[rn] + self.regs[rm]
            self._set_flags_add(self.regs[rn], self.regs[rm], result)
            self.regs[rd] = result & 0xFFFFFFFF
            return
        if instr & 0xF800 == 0x1A00:
            rd = instr & 0x7
            rn = (instr >> 3) & 0x7
            rm = (instr >> 6) & 0x7
            result = self.regs[rn] - self.regs[rm]
            self._set_flags_sub(self.regs[rn], self.regs[rm], result)
            self.regs[rd] = result & 0xFFFFFFFF
            return
        if instr & 0xF800 == 0x4800:
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            pc_aligned = (next_pc + 2) & ~3
            address = (pc_aligned + (imm8 << 2)) & 0xFFFFFFFF
            self.regs[rd] = self.memory.read32(address)
            return
        if instr & 0xF200 == 0x5000:
            rm = (instr >> 6) & 0x7
            rn = (instr >> 3) & 0x7
            rd = instr & 0x7
            address = (self.regs[rn] + self.regs[rm]) & 0xFFFFFFFF
            if instr & 0x0C00 == 0x0000:
                self.memory.write32(address, self.regs[rd])
                return
            if instr & 0x0C00 == 0x0400:
                self.memory.write16(address, self.regs[rd] & 0xFFFF)
                return
            if instr & 0x0C00 == 0x0800:
                self.memory.write8(address, self.regs[rd] & 0xFF)
                return
            if instr & 0x0C00 == 0x0C00:
                self.regs[rd] = self.memory.read32(address)
                return
        if instr & 0xF000 == 0x6000:
            imm5 = (instr >> 6) & 0x1F
            rn = (instr >> 3) & 0x7
            rd = instr & 0x7
            address = (self.regs[rn] + (imm5 << 2)) & 0xFFFFFFFF
            if instr & 0x0800:
                self.regs[rd] = self.memory.read32(address)
            else:
                self.memory.write32(address, self.regs[rd])
            return
        if instr & 0xF000 == 0x7000:
            imm5 = (instr >> 6) & 0x1F
            rn = (instr >> 3) & 0x7
            rd = instr & 0x7
            address = (self.regs[rn] + imm5) & 0xFFFFFFFF
            if instr & 0x0800:
                self.regs[rd] = self.memory.read8(address)
            else:
                self.memory.write8(address, self.regs[rd] & 0xFF)
            return
        if instr & 0xF000 == 0x8000:
            imm5 = (instr >> 6) & 0x1F
            rn = (instr >> 3) & 0x7
            rd = instr & 0x7
            address = (self.regs[rn] + (imm5 << 1)) & 0xFFFFFFFF
            if instr & 0x0800:
                self.regs[rd] = self.memory.read16(address)
            else:
                self.memory.write16(address, self.regs[rd] & 0xFFFF)
            return
        if instr & 0xF000 == 0x9000:
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            address = (self.regs[13] + (imm8 << 2)) & 0xFFFFFFFF
            if instr & 0x0800:
                self.regs[rd] = self.memory.read32(address)
            else:
                self.memory.write32(address, self.regs[rd])
            return
        if instr & 0xF800 == 0xA800:
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            self.regs[rd] = (self.regs[13] + (imm8 << 2)) & 0xFFFFFFFF
            return
        if instr & 0xF000 == 0xD000:
            cond = (instr >> 8) & 0xF
            imm8 = instr & 0xFF
            if cond == 0xF:
                raise NotImplementedError("SVC not supported")
            if self._condition_passed(cond):
                offset = self._sign_extend(imm8 << 1, 9)
                self.pc = (next_pc + offset) & 0xFFFFFFFF
            return
        if instr & 0xF800 == 0xE000:
            imm11 = instr & 0x7FF
            offset = self._sign_extend(imm11 << 1, 12)
            self.pc = (next_pc + offset) & 0xFFFFFFFF
            return
        if instr & 0xFC00 == 0x4000:
            op = (instr >> 6) & 0xF
            rm = (instr >> 3) & 0x7
            rd = instr & 0x7
            if op == 0x0:
                self.regs[rd] &= self.regs[rm]
                self._set_flags_nz(self.regs[rd])
                return
            if op == 0x1:
                self.regs[rd] ^= self.regs[rm]
                self._set_flags_nz(self.regs[rd])
                return
            if op == 0x2:
                shift = self.regs[rm] & 0xFF
                self.regs[rd] = (self.regs[rd] << shift) & 0xFFFFFFFF
                self._set_flags_nz(self.regs[rd])
                return
            if op == 0x3:
                shift = self.regs[rm] & 0xFF
                self.regs[rd] = (self.regs[rd] >> shift) & 0xFFFFFFFF
                self._set_flags_nz(self.regs[rd])
                return
            if op == 0x4:
                shift = self.regs[rm] & 0xFF
                value = self.regs[rd]
                if value & 0x80000000:
                    self.regs[rd] = ((value >> shift) | (0xFFFFFFFF << (32 - shift))) & 0xFFFFFFFF
                else:
                    self.regs[rd] = (value >> shift) & 0xFFFFFFFF
                self._set_flags_nz(self.regs[rd])
                return
            if op == 0x8:
                self._set_flags_sub(self.regs[rd], self.regs[rm], self.regs[rd] - self.regs[rm])
                return
            if op == 0xA:
                self.regs[rd] |= self.regs[rm]
                self._set_flags_nz(self.regs[rd])
                return
        if instr & 0xFFC0 == 0x4040:
            rm = (instr >> 3) & 0x7
            rd = instr & 0x7
            self.regs[rd] = self.regs[rm]
            self._set_flags_nz(self.regs[rd])
            return
        if instr & 0xFFC0 == 0x4280:
            rm = (instr >> 3) & 0x7
            rd = instr & 0x7
            result = self.regs[rd] - self.regs[rm]
            self._set_flags_sub(self.regs[rd], self.regs[rm], result)
            return
        if instr & 0xFC00 == 0x4400:
            rm = (instr >> 3) & 0xF
            rd = (instr & 0x7) | ((instr >> 4) & 0x8)
            self.regs[rd] = (self.regs[rd] + self.regs[rm]) & 0xFFFFFFFF
            return
        if instr & 0xFF87 == 0x4700:
            rm = (instr >> 3) & 0xF
            target = self.regs[rm]
            self.pc = target & ~1
            return
        if instr & 0xFE00 == 0xB400:
            register_list = instr & 0xFF
            include_lr = bool(instr & 0x0100)
            self._push(register_list, include_lr)
            return
        if instr & 0xFE00 == 0xBC00:
            register_list = instr & 0xFF
            include_pc = bool(instr & 0x0100)
            self._pop(register_list, include_pc)
            return
        if instr & 0xF800 == 0xB000:
            imm7 = instr & 0x7F
            if instr & 0x0080:
                self.regs[13] = (self.regs[13] - (imm7 << 2)) & 0xFFFFFFFF
            else:
                self.regs[13] = (self.regs[13] + (imm7 << 2)) & 0xFFFFFFFF
            return
        raise NotImplementedError(f"Unsupported instruction 0x{instr:04X} at 0x{next_pc - 2:08X}")

    def _push(self, register_list: int, include_lr: bool) -> None:
        registers = [i for i in range(8) if register_list & (1 << i)]
        if include_lr:
            registers.append(14)
        for reg in reversed(registers):
            self.regs[13] = (self.regs[13] - 4) & 0xFFFFFFFF
            self.memory.write32(self.regs[13], self.regs[reg])

    def _pop(self, register_list: int, include_pc: bool) -> None:
        registers = [i for i in range(8) if register_list & (1 << i)]
        if include_pc:
            registers.append(15)
        for reg in registers:
            self.regs[reg] = self.memory.read32(self.regs[13])
            self.regs[13] = (self.regs[13] + 4) & 0xFFFFFFFF

    def _set_flags_nz(self, value: int) -> None:
        self.xpsr &= ~(FLAG_NEGATIVE | FLAG_ZERO)
        if value & 0x80000000:
            self.xpsr |= FLAG_NEGATIVE
        if value == 0:
            self.xpsr |= FLAG_ZERO

    def _set_flags_add(self, lhs: int, rhs: int, result: int) -> None:
        self._set_flags_nz(result & 0xFFFFFFFF)
        self.xpsr &= ~(FLAG_CARRY | FLAG_OVERFLOW)
        if result > 0xFFFFFFFF:
            self.xpsr |= FLAG_CARRY
        if (~(lhs ^ rhs) & (lhs ^ result)) & 0x80000000:
            self.xpsr |= FLAG_OVERFLOW

    def _set_flags_sub(self, lhs: int, rhs: int, result: int) -> None:
        self._set_flags_nz(result & 0xFFFFFFFF)
        self.xpsr &= ~(FLAG_CARRY | FLAG_OVERFLOW)
        if lhs >= rhs:
            self.xpsr |= FLAG_CARRY
        if ((lhs ^ rhs) & (lhs ^ result)) & 0x80000000:
            self.xpsr |= FLAG_OVERFLOW

    def _condition_passed(self, cond: int) -> bool:
        z = bool(self.xpsr & FLAG_ZERO)
        n = bool(self.xpsr & FLAG_NEGATIVE)
        c = bool(self.xpsr & FLAG_CARRY)
        v = bool(self.xpsr & FLAG_OVERFLOW)
        if cond == 0x0:
            return z
        if cond == 0x1:
            return not z
        if cond == 0x2:
            return c
        if cond == 0x3:
            return not c
        if cond == 0x4:
            return n
        if cond == 0x5:
            return not n
        if cond == 0x6:
            return v
        if cond == 0x7:
            return not v
        if cond == 0x8:
            return c and not z
        if cond == 0x9:
            return not c or z
        if cond == 0xA:
            return n == v
        if cond == 0xB:
            return n != v
        if cond == 0xC:
            return not z and (n == v)
        if cond == 0xD:
            return z or (n != v)
        return False

    @staticmethod
    def _sign_extend(value: int, bits: int) -> int:
        sign_bit = 1 << (bits - 1)
        return (value ^ sign_bit) - sign_bit


def build_default_memory(
    internal_flash: bytes,
    external_flash: bytes | None = None,
    itcm: bytes | None = None,
) -> MemoryMap:
    memory = MemoryMap()
    flash_size = max(len(internal_flash), 512 * 1024)
    flash = MemoryRegion(
        base=FLASH_BASE,
        size=flash_size,
        data=bytearray(flash_size),
        read_only=False,
    )
    flash.write(FLASH_BASE, internal_flash)
    flash.read_only = True
    memory.add_region(flash)

    if external_flash:
        external_size = max(len(external_flash), 1024 * 1024)
        ext_region = MemoryRegion(
            base=EXTERNAL_FLASH_BASE,
            size=external_size,
            data=bytearray(external_size),
            read_only=False,
        )
        ext_region.write(EXTERNAL_FLASH_BASE, external_flash)
        ext_region.read_only = True
        memory.add_region(ext_region)

    if itcm:
        itcm_size = max(len(itcm), 64 * 1024)
        itcm_region = MemoryRegion(
            base=ITCM_BASE,
            size=itcm_size,
            data=bytearray(itcm_size),
            read_only=False,
        )
        itcm_region.write(ITCM_BASE, itcm)
        itcm_region.read_only = True
        memory.add_region(itcm_region)

    sram = MemoryRegion(
        base=SRAM_BASE,
        size=1380 * 1024,
        data=bytearray(1380 * 1024),
    )
    memory.add_region(sram)
    return memory

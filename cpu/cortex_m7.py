"""
ARM Cortex-M7 CPU Core

Исполнитель декодированных инструкций.
Связывает декодер, регистры, ALU, память и исключения.
"""

from cpu.registers import Registers
from cpu.decoder import Decoder, Op, Condition, Instruction
from cpu.alu import (
    add_with_carry, alu_add, alu_sub, alu_adc, alu_sbc, alu_rsb,
    alu_and, alu_orr, alu_eor, alu_orn, alu_bic, alu_mvn,
    alu_mul, alu_smull, alu_umull, alu_mla, alu_mls,
    alu_sdiv, alu_udiv,
    shift_lsl, shift_lsr, shift_asr, shift_ror, shift_rrx,
    apply_shift, thumb_expand_imm,
    count_leading_zeros, reverse_bits, reverse_bytes,
    reverse_bytes_16, reverse_bytes_signed_16,
    bit_field_insert, bit_field_clear,
    bit_field_extract_unsigned, bit_field_extract_signed,
    signed_saturate, unsigned_saturate,
    extend_byte_signed, extend_halfword_signed,
    extend_byte_unsigned, extend_halfword_unsigned,
    sign_extend, to_signed32, to_unsigned32,
    SHIFT_LSL, SHIFT_LSR, SHIFT_ASR, SHIFT_ROR,
)
from cpu.exceptions import ExceptionManager, ExceptionType
import struct


class CortexM7:
    """
    ARM Cortex-M7 CPU emulator.
    """

    def __init__(self, bus):
        """
        bus: объект системной шины (memory.bus.SystemBus)
             с методами read8/read16/read32/write8/write16/write32
        """
        self.bus = bus
        self.regs = Registers()
        self.decoder = Decoder()
        self.exc_manager = ExceptionManager()

        # IT block state
        self._it_state = 0  # ITSTATE (bits [7:0] from EPSR)

        # Cycle counter (для отладки / синхронизации)
        self.cycle_count = 0

        # Halted state (WFI/WFE)
        self.halted = False

        # Exclusive monitor (для LDREX/STREX)
        self._exclusive_addr = None
        self._exclusive_active = False

        # Debug / trace
        self.trace_enabled = False
        self._last_pc = 0

    # ===============================================================
    # Memory access helpers
    # ===============================================================

    def mem_read8(self, addr):
        return self.bus.read8(addr & 0xFFFFFFFF)

    def mem_read16(self, addr):
        return self.bus.read16(addr & 0xFFFFFFFE)

    def mem_read32(self, addr):
        return self.bus.read32(addr & 0xFFFFFFFC)

    def mem_write8(self, addr, value):
        self.bus.write8(addr & 0xFFFFFFFF, value & 0xFF)

    def mem_write16(self, addr, value):
        self.bus.write16(addr & 0xFFFFFFFE, value & 0xFFFF)

    def mem_write32(self, addr, value):
        self.bus.write32(addr & 0xFFFFFFFC, value & 0xFFFFFFFF)

    # ===============================================================
    # Reset
    # ===============================================================

    def reset(self):
        """Сброс процессора. Загружает SP и PC из vector table."""
        self.exc_manager.reset()
        self._it_state = 0
        self.cycle_count = 0
        self.halted = False
        self._exclusive_active = False

        # Читаем Initial SP и Reset Vector из начала памяти
        initial_sp = self.mem_read32(0x00000000)
        reset_vector = self.mem_read32(0x00000004)

        self.regs.reset(initial_sp, reset_vector)

        if self.trace_enabled:
            print(f"[RESET] SP=0x{initial_sp:08X} PC=0x{reset_vector:08X}")

    # ===============================================================
    # Condition check
    # ===============================================================

    def _check_condition(self, cond):
        """Проверить условие выполнения."""
        if cond == Condition.AL or cond == Condition.NONE:
            return True

        psr = self.regs.psr
        cond_val = cond.value

        if cond_val == 0:    # EQ
            return psr.Z
        elif cond_val == 1:  # NE
            return not psr.Z
        elif cond_val == 2:  # CS/HS
            return psr.C
        elif cond_val == 3:  # CC/LO
            return not psr.C
        elif cond_val == 4:  # MI
            return psr.N
        elif cond_val == 5:  # PL
            return not psr.N
        elif cond_val == 6:  # VS
            return psr.V
        elif cond_val == 7:  # VC
            return not psr.V
        elif cond_val == 8:  # HI
            return psr.C and not psr.Z
        elif cond_val == 9:  # LS
            return not psr.C or psr.Z
        elif cond_val == 10: # GE
            return psr.N == psr.V
        elif cond_val == 11: # LT
            return psr.N != psr.V
        elif cond_val == 12: # GT
            return not psr.Z and (psr.N == psr.V)
        elif cond_val == 13: # LE
            return psr.Z or (psr.N != psr.V)
        elif cond_val == 14: # AL
            return True
        return True

    # ===============================================================
    # IT block management
    # ===============================================================

    def _in_it_block(self):
        return (self._it_state & 0xF) != 0

    def _it_block_condition(self):
        """Текущее условие в IT блоке."""
        if not self._in_it_block():
            return Condition.AL
        top4 = (self._it_state >> 4) & 0xF
        # Бит 0 текущего состояния определяет then/else
        return Condition(top4)

    def _advance_it_state(self):
        """Продвинуть IT state после выполнения инструкции."""
        if self._in_it_block():
            mask = self._it_state & 0xF
            if mask == 0b1000:
                # Последняя инструкция в IT блоке
                self._it_state = 0
            else:
                # Сдвигаем маску влево
                self._it_state = (self._it_state & 0xE0) | ((mask << 1) & 0x1F)

    # ===============================================================
    # Step — один шаг выполнения
    # ===============================================================

    def step(self):
        """
        Выполнить одну инструкцию.
        Возвращает количество циклов (приблизительно).
        """
        # Проверка ожидающих прерываний
        if not self.halted:
            pending = self.exc_manager.get_pending_exception(self.regs)
            if pending is not None:
                self.exc_manager.exception_entry(self, pending)

        if self.halted:
            # WFI/WFE — проверяем прерывания
            pending = self.exc_manager.get_pending_exception(self.regs)
            if pending is not None:
                self.halted = False
                self.exc_manager.exception_entry(self, pending)
            else:
                self.cycle_count += 1
                return 1

        pc = self.regs.pc
        self._last_pc = pc

        # Fetch
        hw1 = self.mem_read16(pc)

        # Determine if 32-bit
        if Decoder._is_thumb32(hw1):
            hw2 = self.mem_read16(pc + 2)
        else:
            hw2 = 0

        # Decode
        inst = self.decoder.decode(hw1, hw2, pc)

        # IT block condition override
        if self._in_it_block() and inst.op != Op.IT:
            inst.cond = self._it_block_condition()

        # Advance PC before execution (so instructions see correct PC+4)
        self.regs.pc = pc + inst.size

        # Check condition
        if inst.cond != Condition.AL and inst.cond != Condition.NONE:
            if not self._check_condition(inst.cond):
                # Condition failed — skip
                if self._in_it_block():
                    self._advance_it_state()
                self.cycle_count += 1
                return 1

        # Execute
        cycles = self._execute(inst)

        # Advance IT state
        if self._in_it_block() and inst.op != Op.IT:
            self._advance_it_state()

        self.cycle_count += cycles

        if self.trace_enabled:
            print(f"[{self.cycle_count:8d}] {inst}")

        return cycles

    # ===============================================================
    # Execute
    # ===============================================================

    def _execute(self, inst):
        """Выполнить декодированную инструкцию."""
        op = inst.op

        # Dispatch table
        handler = self._dispatch.get(op)
        if handler:
            return handler(self, inst)
        else:
            if self.trace_enabled:
                print(f"[WARN] Unimplemented: {inst}")
            return 1

    # ---------------------------------------------------------------
    # Data Processing — Immediate / Register
    # ---------------------------------------------------------------

    def _exec_mov(self, inst):
        if inst.imm is not None:
            if inst.size == 4 and inst.op in (Op.MOV, Op.MOVS):
                # Thumb-2 modified immediate
                val, carry = thumb_expand_imm(inst.imm, self.regs.psr.C)
            else:
                val = inst.imm
                carry = self.regs.psr.C
        elif inst.rm is not None:
            val = self.regs[inst.rm]
            if inst.shift_n > 0 or inst.shift_type != SHIFT_LSL:
                val, carry = apply_shift(val, inst.shift_type, inst.shift_n, self.regs.psr.C)
            else:
                carry = self.regs.psr.C
        else:
            return 1

        self.regs[inst.rd] = val

        if inst.setflags or inst.op in (Op.MOVS,):
            self.regs.psr.update_flags_nz(val)
            self.regs.psr.C = carry

        if inst.rd == 15:
            self._branch_written()

        return 1

    def _exec_movw(self, inst):
        """MOVW — 16-bit immediate в нижние 16 бит."""
        self.regs[inst.rd] = inst.imm & 0xFFFF
        return 1

    def _exec_movt(self, inst):
        """MOVT — 16-bit immediate в верхние 16 бит."""
        old = self.regs[inst.rd]
        self.regs[inst.rd] = (old & 0x0000FFFF) | ((inst.imm & 0xFFFF) << 16)
        return 1

    def _exec_mvn(self, inst):
        if inst.imm is not None:
            val, carry = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            val = self.regs[inst.rm]
            val, carry = apply_shift(val, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        result = alu_mvn(val)
        self.regs[inst.rd] = result

        if inst.setflags or inst.op in (Op.MVNS,):
            self.regs.psr.update_flags_nz(result)
            self.regs.psr.C = carry

        return 1

    def _exec_add(self, inst):
        a = self.regs[inst.rn] if inst.rn is not None else 0

        if inst.imm is not None:
            if inst.size == 4 and inst.op in (Op.ADD, Op.ADDS) and inst.rn not in (13, 15):
                # Could be modified immediate
                if inst.rd is not None and inst.setflags:
                    b, _ = thumb_expand_imm(inst.imm, self.regs.psr.C)
                else:
                    b = inst.imm
            else:
                b = inst.imm
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, _ = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        if inst.rn == 15:
            # PC-relative: align PC to 4
            a = (self._last_pc + 4) & 0xFFFFFFFC

        result, carry, overflow = alu_add(a, b)

        if inst.rd is not None:
            self.regs[inst.rd] = result
            if inst.rd == 15:
                self._branch_written()

        if inst.setflags or inst.op in (Op.ADDS,):
            self.regs.psr.update_flags_nzcv(result, carry, overflow)

        return 1

    def _exec_adc(self, inst):
        a = self.regs[inst.rn]
        c_in = self.regs.psr.C

        if inst.imm is not None:
            b, _ = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, _ = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            b = 0

        result, carry, overflow = alu_adc(a, b, c_in)
        self.regs[inst.rd] = result

        if inst.setflags or inst.op in (Op.ADCS,):
            self.regs.psr.update_flags_nzcv(result, carry, overflow)

        return 1

    def _exec_sub(self, inst):
        a = self.regs[inst.rn] if inst.rn is not None else 0

        if inst.imm is not None:
            if inst.size == 4 and inst.setflags:
                b, _ = thumb_expand_imm(inst.imm, self.regs.psr.C)
            else:
                b = inst.imm
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, _ = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        if inst.rn == 15:
            a = (self._last_pc + 4) & 0xFFFFFFFC

        result, carry, overflow = alu_sub(a, b)

        if inst.rd is not None:
            self.regs[inst.rd] = result
            if inst.rd == 15:
                self._branch_written()

        if inst.setflags or inst.op in (Op.SUBS,):
            self.regs.psr.update_flags_nzcv(result, carry, overflow)

        return 1

    def _exec_sbc(self, inst):
        a = self.regs[inst.rn]
        c_in = self.regs.psr.C

        if inst.imm is not None:
            b, _ = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, _ = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            b = 0

        result, carry, overflow = alu_sbc(a, b, c_in)
        self.regs[inst.rd] = result

        if inst.setflags or inst.op in (Op.SBCS,):
            self.regs.psr.update_flags_nzcv(result, carry, overflow)

        return 1

    def _exec_rsb(self, inst):
        a = self.regs[inst.rn]

        if inst.imm is not None:
            b = inst.imm
        elif inst.rm is not None:
            b = self.regs[inst.rm]
        else:
            b = 0

        result, carry, overflow = alu_rsb(a, b)
        self.regs[inst.rd] = result

        if inst.setflags or inst.op in (Op.RSBS,):
            self.regs.psr.update_flags_nzcv(result, carry, overflow)

        return 1

    # ---------------------------------------------------------------
    # Logic
    # ---------------------------------------------------------------

    def _exec_and(self, inst):
        a = self.regs[inst.rn]
        if inst.imm is not None:
            b, carry = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, carry = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        result = alu_and(a, b)
        if inst.rd is not None:
            self.regs[inst.rd] = result

        if inst.setflags or inst.op in (Op.ANDS,):
            self.regs.psr.update_flags_nz(result)
            self.regs.psr.C = carry

        return 1

    def _exec_orr(self, inst):
        a = self.regs[inst.rn] if inst.rn is not None else 0
        if inst.imm is not None:
            b, carry = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, carry = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        result = alu_orr(a, b)
        if inst.rd is not None:
            self.regs[inst.rd] = result

        if inst.setflags or inst.op in (Op.ORRS,):
            self.regs.psr.update_flags_nz(result)
            self.regs.psr.C = carry

        return 1

    def _exec_eor(self, inst):
        a = self.regs[inst.rn]
        if inst.imm is not None:
            b, carry = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, carry = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        result = alu_eor(a, b)
        if inst.rd is not None:
            self.regs[inst.rd] = result

        if inst.setflags or inst.op in (Op.EORS,):
            self.regs.psr.update_flags_nz(result)
            self.regs.psr.C = carry

        return 1

    def _exec_orn(self, inst):
        a = self.regs[inst.rn] if inst.rn is not None else 0
        if inst.imm is not None:
            b, carry = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, carry = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        result = alu_orn(a, b)
        if inst.rd is not None:
            self.regs[inst.rd] = result

        if inst.setflags or inst.op in (Op.ORNS,):
            self.regs.psr.update_flags_nz(result)
            self.regs.psr.C = carry

        return 1

    def _exec_bic(self, inst):
        a = self.regs[inst.rn]
        if inst.imm is not None:
            b, carry = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, carry = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        result = alu_bic(a, b)
        self.regs[inst.rd] = result

        if inst.setflags or inst.op in (Op.BICS,):
            self.regs.psr.update_flags_nz(result)
            self.regs.psr.C = carry

        return 1

    # ---------------------------------------------------------------
    # Compare / Test
    # ---------------------------------------------------------------

    def _exec_cmp(self, inst):
        a = self.regs[inst.rn]
        if inst.imm is not None:
            if inst.size == 4:
                b, _ = thumb_expand_imm(inst.imm, self.regs.psr.C)
            else:
                b = inst.imm
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, _ = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        result, carry, overflow = alu_sub(a, b)
        self.regs.psr.update_flags_nzcv(result, carry, overflow)
        return 1

    def _exec_cmn(self, inst):
        a = self.regs[inst.rn]
        if inst.imm is not None:
            b, _ = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            b = self.regs[inst.rm]
        else:
            return 1

        result, carry, overflow = alu_add(a, b)
        self.regs.psr.update_flags_nzcv(result, carry, overflow)
        return 1

    def _exec_tst(self, inst):
        a = self.regs[inst.rn]
        if inst.imm is not None:
            b, carry = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, carry = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        result = alu_and(a, b)
        self.regs.psr.update_flags_nz(result)
        self.regs.psr.C = carry
        return 1

    def _exec_teq(self, inst):
        a = self.regs[inst.rn]
        if inst.imm is not None:
            b, carry = thumb_expand_imm(inst.imm, self.regs.psr.C)
        elif inst.rm is not None:
            b = self.regs[inst.rm]
            b, carry = apply_shift(b, inst.shift_type, inst.shift_n, self.regs.psr.C)
        else:
            return 1

        result = alu_eor(a, b)
        self.regs.psr.update_flags_nz(result)
        self.regs.psr.C = carry
        return 1

    # ---------------------------------------------------------------
    # Shifts (register-based)
    # ---------------------------------------------------------------

    def _exec_shift_reg(self, inst):
        """LSL/LSR/ASR/ROR by register."""
        value = self.regs[inst.rn]
        if inst.rs is not None:
            amount = self.regs[inst.rs] & 0xFF
        elif inst.rm is not None:
            amount = self.regs[inst.rm] & 0xFF
        else:
            amount = 0

        carry_in = self.regs.psr.C

        if inst.op in (Op.LSL, Op.LSLS):
            result, carry = shift_lsl(value, amount, carry_in)
        elif inst.op in (Op.LSR, Op.LSRS):
            result, carry = shift_lsr(value, amount, carry_in)
        elif inst.op in (Op.ASR, Op.ASRS):
            result, carry = shift_asr(value, amount, carry_in)
        elif inst.op in (Op.ROR, Op.RORS):
            result, carry = shift_ror(value, amount, carry_in)
        else:
            result, carry = value, carry_in

        self.regs[inst.rd] = result

        if inst.setflags or inst.op.name.endswith('S'):
            self.regs.psr.update_flags_nz(result)
            self.regs.psr.C = carry

        return 1

    # ---------------------------------------------------------------
    # Multiply / Divide
    # ---------------------------------------------------------------

    def _exec_mul(self, inst):
        a = self.regs[inst.rn]
        b = self.regs[inst.rm]
        result = alu_mul(a, b)
        self.regs[inst.rd] = result
        if inst.setflags or inst.op == Op.MULS:
            self.regs.psr.update_flags_nz(result)
        return 3

    def _exec_mla(self, inst):
        a = self.regs[inst.rn]
        b = self.regs[inst.rm]
        acc = self.regs[inst.rs] if inst.rs is not None else 0
        result = alu_mla(a, b, acc)
        self.regs[inst.rd] = result
        return 3

    def _exec_mls(self, inst):
        a = self.regs[inst.rn]
        b = self.regs[inst.rm]
        acc = self.regs[inst.rs] if inst.rs is not None else 0
        result = alu_mls(a, b, acc)
        self.regs[inst.rd] = result
        return 3

    def _exec_smull(self, inst):
        a = self.regs[inst.rn]
        b = self.regs[inst.rm]
        lo, hi = alu_smull(a, b)
        self.regs[inst.rdlo] = lo
        self.regs[inst.rdhi] = hi
        return 4

    def _exec_umull(self, inst):
        a = self.regs[inst.rn]
        b = self.regs[inst.rm]
        lo, hi = alu_umull(a, b)
        self.regs[inst.rdlo] = lo
        self.regs[inst.rdhi] = hi
        return 4

    def _exec_smlal(self, inst):
        a = self.regs[inst.rn]
        b = self.regs[inst.rm]
        lo, hi = alu_smull(a, b)
        acc = (self.regs[inst.rdhi] << 32) | self.regs[inst.rdlo]
        result = acc + ((hi << 32) | lo)
        self.regs[inst.rdlo] = result & 0xFFFFFFFF
        self.regs[inst.rdhi] = (result >> 32) & 0xFFFFFFFF
        return 4

    def _exec_umlal(self, inst):
        a = self.regs[inst.rn]
        b = self.regs[inst.rm]
        lo, hi = alu_umull(a, b)
        acc = (self.regs[inst.rdhi] << 32) | self.regs[inst.rdlo]
        result = acc + ((hi << 32) | lo)
        self.regs[inst.rdlo] = result & 0xFFFFFFFF
        self.regs[inst.rdhi] = (result >> 32) & 0xFFFFFFFF
        return 4

    def _exec_sdiv(self, inst):
        self.regs[inst.rd] = alu_sdiv(self.regs[inst.rn], self.regs[inst.rm])
        return 12

    def _exec_udiv(self, inst):
        self.regs[inst.rd] = alu_udiv(self.regs[inst.rn], self.regs[inst.rm])
        return 12

    # ---------------------------------------------------------------
    # Load / Store
    # ---------------------------------------------------------------

    def _calc_load_store_addr(self, inst):
        """Вычислить адрес для load/store и обработать writeback."""
        if inst.rn is not None:
            base = self.regs[inst.rn]
            if inst.rn == 15:
                base = (self._last_pc + 4) & 0xFFFFFFFC
        else:
            base = 0

        if inst.rm is not None:
            offset = self.regs[inst.rm]
            offset, _ = apply_shift(offset, inst.shift_type, inst.shift_n, False)
        elif inst.imm is not None:
            offset = inst.imm
        else:
            offset = 0

        if inst.add:
            offset_addr = (base + offset) & 0xFFFFFFFF
        else:
            offset_addr = (base - offset) & 0xFFFFFFFF

        if inst.index:
            addr = offset_addr
        else:
            addr = base

        # Writeback
        if inst.wback:
            self.regs[inst.rn] = offset_addr

        return addr

    def _exec_ldr(self, inst):
        addr = self._calc_load_store_addr(inst)
        value = self.mem_read32(addr)
        rt = inst.rt if inst.rt is not None else inst.rd
        self.regs[rt] = value
        if rt == 15:
            self._branch_written()
        return 2

    def _exec_ldr_lit(self, inst):
        """LDR from literal pool (PC-relative)."""
        base = (self._last_pc + 4) & 0xFFFFFFFC
        if inst.add is False:
            addr = base - inst.imm
        else:
            addr = base + inst.imm
        value = self.mem_read32(addr)
        rt = inst.rt if inst.rt is not None else inst.rd
        self.regs[rt] = value
        if rt == 15:
            self._branch_written()
        return 2

    def _exec_ldrb(self, inst):
        addr = self._calc_load_store_addr(inst)
        value = self.mem_read8(addr)
        rt = inst.rt if inst.rt is not None else inst.rd
        self.regs[rt] = value
        return 2

    def _exec_ldrh(self, inst):
        addr = self._calc_load_store_addr(inst)
        value = self.mem_read16(addr)
        rt = inst.rt if inst.rt is not None else inst.rd
        self.regs[rt] = value
        return 2

    def _exec_ldrsb(self, inst):
        addr = self._calc_load_store_addr(inst)
        value = self.mem_read8(addr)
        value = sign_extend(value, 8)
        rt = inst.rt if inst.rt is not None else inst.rd
        self.regs[rt] = value
        return 2

    def _exec_ldrsh(self, inst):
        addr = self._calc_load_store_addr(inst)
        value = self.mem_read16(addr)
        value = sign_extend(value, 16)
        rt = inst.rt if inst.rt is not None else inst.rd
        self.regs[rt] = value
        return 2

    def _exec_ldrd(self, inst):
        base = self.regs[inst.rn]
        offset = inst.imm if inst.imm else 0

        if inst.add:
            offset_addr = (base + offset) & 0xFFFFFFFF
        else:
            offset_addr = (base - offset) & 0xFFFFFFFF

        addr = offset_addr if inst.index else base

        self.regs[inst.rt] = self.mem_read32(addr)
        self.regs[inst.rt2] = self.mem_read32(addr + 4)

        if inst.wback:
            self.regs[inst.rn] = offset_addr

        return 3

    def _exec_str(self, inst):
        addr = self._calc_load_store_addr(inst)
        rt = inst.rt if inst.rt is not None else inst.rd
        self.mem_write32(addr, self.regs[rt])
        return 2

    def _exec_strb(self, inst):
        addr = self._calc_load_store_addr(inst)
        rt = inst.rt if inst.rt is not None else inst.rd
        self.mem_write8(addr, self.regs[rt])
        return 2

    def _exec_strh(self, inst):
        addr = self._calc_load_store_addr(inst)
        rt = inst.rt if inst.rt is not None else inst.rd
        self.mem_write16(addr, self.regs[rt])
        return 2

    def _exec_strd(self, inst):
        base = self.regs[inst.rn]
        offset = inst.imm if inst.imm else 0

        if inst.add:
            offset_addr = (base + offset) & 0xFFFFFFFF
        else:
            offset_addr = (base - offset) & 0xFFFFFFFF

        addr = offset_addr if inst.index else base

        self.mem_write32(addr, self.regs[inst.rt])
        self.mem_write32(addr + 4, self.regs[inst.rt2])

        if inst.wback:
            self.regs[inst.rn] = offset_addr

        return 3

    # ---------------------------------------------------------------
    # Load/Store Multiple
    # ---------------------------------------------------------------

    def _exec_ldm(self, inst):
        addr = self.regs[inst.rn]
        for reg in sorted(inst.register_list):
            self.regs[reg] = self.mem_read32(addr)
            addr += 4
        if inst.wback and inst.rn not in inst.register_list:
            self.regs[inst.rn] = addr
        if 15 in inst.register_list:
            self._branch_written()
        return 1 + len(inst.register_list)

    def _exec_ldmdb(self, inst):
        addr = self.regs[inst.rn] - 4 * len(inst.register_list)
        base = addr
        for reg in sorted(inst.register_list):
            self.regs[reg] = self.mem_read32(addr)
            addr += 4
        if inst.wback:
            self.regs[inst.rn] = base
        if 15 in inst.register_list:
            self._branch_written()
        return 1 + len(inst.register_list)

    def _exec_stm(self, inst):
        addr = self.regs[inst.rn]
        for reg in sorted(inst.register_list):
            self.mem_write32(addr, self.regs[reg])
            addr += 4
        if inst.wback:
            self.regs[inst.rn] = addr
        return 1 + len(inst.register_list)

    def _exec_stmdb(self, inst):
        addr = self.regs[inst.rn] - 4 * len(inst.register_list)
        base = addr
        for reg in sorted(inst.register_list):
            self.mem_write32(addr, self.regs[reg])
            addr += 4
        if inst.wback:
            self.regs[inst.rn] = base
        return 1 + len(inst.register_list)

    # ---------------------------------------------------------------
    # PUSH / POP
    # ---------------------------------------------------------------

    def _exec_push(self, inst):
        regs = sorted(inst.register_list, reverse=True)
        sp = self.regs.sp - 4 * len(regs)
        addr = sp
        for reg in sorted(inst.register_list):
            self.mem_write32(addr, self.regs[reg])
            addr += 4
        self.regs.sp = sp
        return 1 + len(regs)

    def _exec_pop(self, inst):
        addr = self.regs.sp
        for reg in sorted(inst.register_list):
            self.regs[reg] = self.mem_read32(addr)
            addr += 4
        self.regs.sp = addr
        if 15 in inst.register_list:
            self._branch_written()
        return 1 + len(inst.register_list)

    # ---------------------------------------------------------------
    # Branch
    # ---------------------------------------------------------------

    def _exec_b(self, inst):
        target = (self._last_pc + 4 + inst.imm) & 0xFFFFFFFF
        self.regs.pc = target & 0xFFFFFFFE
        return 1

    def _exec_bl(self, inst):
        target = (self._last_pc + 4 + inst.imm) & 0xFFFFFFFF
        self.regs.lr = (self._last_pc + 4 + 1) & 0xFFFFFFFF  # return addr with Thumb bit
        # For 32-bit BL, return address is PC + 4 (next instruction)
        self.regs.lr = (self.regs.pc | 1) & 0xFFFFFFFF
        self.regs.pc = target & 0xFFFFFFFE
        return 1

    def _exec_bx(self, inst):
        target = self.regs[inst.rm]
        # Check for EXC_RETURN
        if ExceptionManager.is_exc_return(target):
            self.exc_manager.exception_return(self, target)
            return 1
        self.regs.branch(target)
        return 1

    def _exec_blx(self, inst):
        target = self.regs[inst.rm]
        self.regs.lr = (self.regs.pc | 1) & 0xFFFFFFFF
        self.regs.branch(target)
        return 1

    def _exec_cbz(self, inst):
        val = self.regs[inst.rn]
        if val == 0:
            target = (self._last_pc + 4 + inst.imm) & 0xFFFFFFFF
            self.regs.pc = target & 0xFFFFFFFE
        return 1

    def _exec_cbnz(self, inst):
        val = self.regs[inst.rn]
        if val != 0:
            target = (self._last_pc + 4 + inst.imm) & 0xFFFFFFFF
            self.regs.pc = target & 0xFFFFFFFE
        return 1

    def _exec_tbb(self, inst):
        base = self.regs[inst.rn]
        if inst.rn == 15:
            base = self._last_pc + 4
        index = self.regs[inst.rm]
        offset = self.mem_read8(base + index) * 2
        self.regs.pc = (self._last_pc + 4 + offset) & 0xFFFFFFFE
        return 2

    def _exec_tbh(self, inst):
        base = self.regs[inst.rn]
        if inst.rn == 15:
            base = self._last_pc + 4
        index = self.regs[inst.rm]
        offset = self.mem_read16(base + index * 2) * 2
        self.regs.pc = (self._last_pc + 4 + offset) & 0xFFFFFFFE
        return 2

    # ---------------------------------------------------------------
    # IT block
    # ---------------------------------------------------------------

    def _exec_it(self, inst):
        self._it_state = (inst.firstcond << 4) | inst.mask
        return 1

    # ---------------------------------------------------------------
    # Extend operations
    # ---------------------------------------------------------------

    def _exec_sxtb(self, inst):
        val = self.regs[inst.rm]
        self.regs[inst.rd] = extend_byte_signed(val, inst.rotation)
        return 1

    def _exec_sxth(self, inst):
        val = self.regs[inst.rm]
        self.regs[inst.rd] = extend_halfword_signed(val, inst.rotation)
        return 1

    def _exec_uxtb(self, inst):
        val = self.regs[inst.rm]
        self.regs[inst.rd] = extend_byte_unsigned(val, inst.rotation)
        return 1

    def _exec_uxth(self, inst):
        val = self.regs[inst.rm]
        self.regs[inst.rd] = extend_halfword_unsigned(val, inst.rotation)
        return 1

    def _exec_sxtab(self, inst):
        rn_val = self.regs[inst.rn] if inst.rn is not None else 0
        rm_val = self.regs[inst.rm]
        extended = extend_byte_signed(rm_val, inst.rotation)
        self.regs[inst.rd] = (rn_val + extended) & 0xFFFFFFFF
        return 1

    def _exec_sxtah(self, inst):
        rn_val = self.regs[inst.rn] if inst.rn is not None else 0
        rm_val = self.regs[inst.rm]
        extended = extend_halfword_signed(rm_val, inst.rotation)
        self.regs[inst.rd] = (rn_val + extended) & 0xFFFFFFFF
        return 1

    def _exec_uxtab(self, inst):
        rn_val = self.regs[inst.rn] if inst.rn is not None else 0
        rm_val = self.regs[inst.rm]
        extended = extend_byte_unsigned(rm_val, inst.rotation)
        self.regs[inst.rd] = (rn_val + extended) & 0xFFFFFFFF
        return 1

    def _exec_uxtah(self, inst):
        rn_val = self.regs[inst.rn] if inst.rn is not None else 0
        rm_val = self.regs[inst.rm]
        extended = extend_halfword_unsigned(rm_val, inst.rotation)
        self.regs[inst.rd] = (rn_val + extended) & 0xFFFFFFFF
        return 1

    # ---------------------------------------------------------------
    # Bit manipulation
    # ---------------------------------------------------------------

    def _exec_clz(self, inst):
        self.regs[inst.rd] = count_leading_zeros(self.regs[inst.rm])
        return 1

    def _exec_rbit(self, inst):
        self.regs[inst.rd] = reverse_bits(self.regs[inst.rm])
        return 1

    def _exec_rev(self, inst):
        self.regs[inst.rd] = reverse_bytes(self.regs[inst.rm])
        return 1

    def _exec_rev16(self, inst):
        self.regs[inst.rd] = reverse_bytes_16(self.regs[inst.rm])
        return 1

    def _exec_revsh(self, inst):
        self.regs[inst.rd] = reverse_bytes_signed_16(self.regs[inst.rm])
        return 1

    def _exec_bfi(self, inst):
        dest = self.regs[inst.rd]
        source = self.regs[inst.rn]
        self.regs[inst.rd] = bit_field_insert(dest, source, inst.lsb, inst.width)
        return 1

    def _exec_bfc(self, inst):
        dest = self.regs[inst.rd]
        self.regs[inst.rd] = bit_field_clear(dest, inst.lsb, inst.width)
        return 1

    def _exec_ubfx(self, inst):
        val = self.regs[inst.rn]
        self.regs[inst.rd] = bit_field_extract_unsigned(val, inst.lsb, inst.width)
        return 1

    def _exec_sbfx(self, inst):
        val = self.regs[inst.rn]
        self.regs[inst.rd] = bit_field_extract_signed(val, inst.lsb, inst.width)
        return 1

    # ---------------------------------------------------------------
    # Saturation
    # ---------------------------------------------------------------

    def _exec_ssat(self, inst):
        val = self.regs[inst.rn]
        val, _ = apply_shift(val, inst.shift_type, inst.shift_n, False)
        result, saturated = signed_saturate(val, inst.sat_imm)
        self.regs[inst.rd] = result
        if saturated:
            self.regs.psr.Q = True
        return 1

    def _exec_usat(self, inst):
        val = self.regs[inst.rn]
        val, _ = apply_shift(val, inst.shift_type, inst.shift_n, False)
        result, saturated = unsigned_saturate(val, inst.sat_imm)
        self.regs[inst.rd] = result
        if saturated:
            self.regs.psr.Q = True
        return 1

    # ---------------------------------------------------------------
    # System
    # ---------------------------------------------------------------

    def _exec_msr(self, inst):
        val = self.regs[inst.rn]
        sysm = inst.imm

        if sysm == 0 or sysm == 1 or sysm == 2 or sysm == 3:
            # xPSR variants — write APSR flags
            mask = 0xF8000000  # N, Z, C, V, Q
            self.regs.psr.value = (self.regs.psr.value & ~mask) | (val & mask)
        elif sysm == 8:
            self.regs.msp = val
        elif sysm == 9:
            self.regs.psp = val
        elif sysm == 16:
            self.regs.primask = val & 1
        elif sysm == 17:
            self.regs.basepri = val & 0xFF
        elif sysm == 18:
            # BASEPRI_MAX: only raise priority (lower number)
            new = val & 0xFF
            if new != 0 and (self.regs.basepri == 0 or new < self.regs.basepri):
                self.regs.basepri = new
        elif sysm == 19:
            self.regs.faultmask = val & 1
        elif sysm == 20:
            self.regs.control = val & 0x3
        return 2

    def _exec_mrs(self, inst):
        sysm = inst.imm

        if sysm == 0:  # APSR
            self.regs[inst.rd] = self.regs.psr.value & 0xF8000000
        elif sysm == 1:  # IAPSR
            self.regs[inst.rd] = self.regs.psr.value & 0xF80001FF
        elif sysm == 2:  # EAPSR
            self.regs[inst.rd] = self.regs.psr.value & 0xFE00FC00
        elif sysm == 3:  # xPSR
            self.regs[inst.rd] = self.regs.psr.value
        elif sysm == 5:  # IPSR
            self.regs[inst.rd] = self.regs.psr.value & 0x1FF
        elif sysm == 6:  # EPSR
            self.regs[inst.rd] = self.regs.psr.value & 0x0700FC00
        elif sysm == 7:  # IEPSR
            self.regs[inst.rd] = self.regs.psr.value & 0x0700FDFF
        elif sysm == 8:
            self.regs[inst.rd] = self.regs.msp
        elif sysm == 9:
            self.regs[inst.rd] = self.regs.psp
        elif sysm == 16:
            self.regs[inst.rd] = self.regs.primask
        elif sysm == 17:
            self.regs[inst.rd] = self.regs.basepri
        elif sysm == 18:
            self.regs[inst.rd] = self.regs.basepri  # BASEPRI_MAX reads same
        elif sysm == 19:
            self.regs[inst.rd] = self.regs.faultmask
        elif sysm == 20:
            self.regs[inst.rd] = self.regs.control
        else:
            self.regs[inst.rd] = 0
        return 2

    def _exec_svc(self, inst):
        self.exc_manager.set_pending(ExceptionType.SVCALL)
        return 1

    def _exec_bkpt(self, inst):
        if self.trace_enabled:
            print(f"[BKPT] #{inst.imm} at 0x{self._last_pc:08X}")
            print(self.regs.dump())
        return 1

    def _exec_cpsie(self, inst):
        if inst.imm & 0x2:  # i flag
            self.regs.primask = 0
        if inst.imm & 0x1:  # f flag
            self.regs.faultmask = 0
        return 1

    def _exec_cpsid(self, inst):
        if inst.imm & 0x2:  # i flag
            self.regs.primask = 1
        if inst.imm & 0x1:  # f flag
            self.regs.faultmask = 1
        return 1

    # ---------------------------------------------------------------
    # Exclusive access
    # ---------------------------------------------------------------

    def _exec_ldrex(self, inst):
        addr = (self.regs[inst.rn] + (inst.imm or 0)) & 0xFFFFFFFF
        self.regs[inst.rt] = self.mem_read32(addr)
        self._exclusive_addr = addr
        self._exclusive_active = True
        return 2

    def _exec_ldrexb(self, inst):
        addr = self.regs[inst.rn]
        self.regs[inst.rt] = self.mem_read8(addr)
        self._exclusive_addr = addr
        self._exclusive_active = True
        return 2

    def _exec_ldrexh(self, inst):
        addr = self.regs[inst.rn]
        self.regs[inst.rt] = self.mem_read16(addr)
        self._exclusive_addr = addr
        self._exclusive_active = True
        return 2

    def _exec_strex(self, inst):
        addr = (self.regs[inst.rn] + (inst.imm or 0)) & 0xFFFFFFFF
        if self._exclusive_active and self._exclusive_addr == addr:
            self.mem_write32(addr, self.regs[inst.rt])
            self.regs[inst.rd] = 0  # Success
            self._exclusive_active = False
        else:
            self.regs[inst.rd] = 1  # Failure
        return 2

    def _exec_strexb(self, inst):
        addr = self.regs[inst.rn]
        if self._exclusive_active:
            self.mem_write8(addr, self.regs[inst.rt])
            self.regs[inst.rd] = 0
            self._exclusive_active = False
        else:
            self.regs[inst.rd] = 1
        return 2

    def _exec_strexh(self, inst):
        addr = self.regs[inst.rn]
        if self._exclusive_active:
            self.mem_write16(addr, self.regs[inst.rt])
            self.regs[inst.rd] = 0
            self._exclusive_active = False
        else:
            self.regs[inst.rd] = 1
        return 2

    def _exec_clrex(self, inst):
        self._exclusive_active = False
        return 1

    # ---------------------------------------------------------------
    # Hints / Barriers
    # ---------------------------------------------------------------

    def _exec_nop(self, inst):
        return 1

    def _exec_wfi(self, inst):
        self.halted = True
        return 1

    def _exec_wfe(self, inst):
        # Simplified: just act like NOP
        return 1

    def _exec_dmb(self, inst):
        return 1  # Memory barrier — NOP in emulator

    def _exec_dsb(self, inst):
        return 1

    def _exec_isb(self, inst):
        return 1

    def _exec_yield(self, inst):
        return 1

    def _exec_sev(self, inst):
        return 1

    # ---------------------------------------------------------------
    # Unknown / Undefined
    # ---------------------------------------------------------------

    def _exec_unknown(self, inst):
        if self.trace_enabled:
            print(f"[UNKNOWN] 0x{inst.raw:08X} at 0x{inst.address:08X}")
            print(self.regs.dump())
        # Trigger UsageFault or HardFault
        self.exc_manager.set_pending(ExceptionType.HARDFAULT)
        return 1

    def _exec_undefined(self, inst):
        if self.trace_enabled:
            print(f"[UNDEF] 0x{inst.raw:08X} at 0x{inst.address:08X}")
        self.exc_manager.set_pending(ExceptionType.USAGEFAULT)
        return 1

    # ---------------------------------------------------------------
    # Branch helper
    # ---------------------------------------------------------------

    def _branch_written(self):
        """Вызывается когда PC изменён через запись в R15."""
        target = self.regs.pc
        if ExceptionManager.is_exc_return(target):
            self.exc_manager.exception_return(self, target)

    # ===============================================================
    # Dispatch table
    # ===============================================================

    _dispatch = {
        # MOV variants
        Op.MOV: _exec_mov,
        Op.MOVS: _exec_mov,
        Op.MOVW: _exec_movw,
        Op.MOVT: _exec_movt,
        Op.MVN: _exec_mvn,
        Op.MVNS: _exec_mvn,

        # Arithmetic
        Op.ADD: _exec_add,
        Op.ADDS: _exec_add,
        Op.ADC: _exec_adc,
        Op.ADCS: _exec_adc,
        Op.SUB: _exec_sub,
        Op.SUBS: _exec_sub,
        Op.SBC: _exec_sbc,
        Op.SBCS: _exec_sbc,
        Op.RSB: _exec_rsb,
        Op.RSBS: _exec_rsb,

        # Logic
        Op.AND: _exec_and,
        Op.ANDS: _exec_and,
        Op.ORR: _exec_orr,
        Op.ORRS: _exec_orr,
        Op.EOR: _exec_eor,
        Op.EORS: _exec_eor,
        Op.ORN: _exec_orn,
        Op.ORNS: _exec_orn,
        Op.BIC: _exec_bic,
        Op.BICS: _exec_bic,

        # Compare / Test
        Op.CMP: _exec_cmp,
        Op.CMN: _exec_cmn,
        Op.TST: _exec_tst,
        Op.TEQ: _exec_teq,

        # Shifts
        Op.LSL: _exec_shift_reg,
        Op.LSLS: _exec_shift_reg,
        Op.LSR: _exec_shift_reg,
        Op.LSRS: _exec_shift_reg,
        Op.ASR: _exec_shift_reg,
        Op.ASRS: _exec_shift_reg,
        Op.ROR: _exec_shift_reg,
        Op.RORS: _exec_shift_reg,

        # Multiply / Divide
        Op.MUL: _exec_mul,
        Op.MULS: _exec_mul,
        Op.MLA: _exec_mla,
        Op.MLS: _exec_mls,
        Op.SMULL: _exec_smull,
        Op.UMULL: _exec_umull,
        Op.SMLAL: _exec_smlal,
        Op.UMLAL: _exec_umlal,
        Op.SDIV: _exec_sdiv,
        Op.UDIV: _exec_udiv,

        # Load
        Op.LDR: _exec_ldr,
        Op.LDR_LIT: _exec_ldr_lit,
        Op.LDRB: _exec_ldrb,
        Op.LDRH: _exec_ldrh,
        Op.LDRSB: _exec_ldrsb,
        Op.LDRSH: _exec_ldrsh,
        Op.LDRD: _exec_ldrd,
        Op.LDM: _exec_ldm,
        Op.LDMDB: _exec_ldmdb,

        # Store
        Op.STR: _exec_str,
        Op.STRB: _exec_strb,
        Op.STRH: _exec_strh,
        Op.STRD: _exec_strd,
        Op.STM: _exec_stm,
        Op.STMDB: _exec_stmdb,

        # Stack
        Op.PUSH: _exec_push,
        Op.POP: _exec_pop,

        # Branch
        Op.B: _exec_b,
        Op.BL: _exec_bl,
        Op.BX: _exec_bx,
        Op.BLX: _exec_blx,
        Op.CBZ: _exec_cbz,
        Op.CBNZ: _exec_cbnz,
        Op.TBB: _exec_tbb,
        Op.TBH: _exec_tbh,

        # IT
        Op.IT: _exec_it,

        # Extend
        Op.SXTB: _exec_sxtb,
        Op.SXTH: _exec_sxth,
        Op.UXTB: _exec_uxtb,
        Op.UXTH: _exec_uxth,
        Op.SXTAB: _exec_sxtab,
        Op.SXTAH: _exec_sxtah,
        Op.UXTAB: _exec_uxtab,
        Op.UXTAH: _exec_uxtah,

        # Bit manipulation
        Op.CLZ: _exec_clz,
        Op.RBIT: _exec_rbit,
        Op.REV: _exec_rev,
        Op.REV16: _exec_rev16,
        Op.REVSH: _exec_revsh,
        Op.BFI: _exec_bfi,
        Op.BFC: _exec_bfc,
        Op.UBFX: _exec_ubfx,
        Op.SBFX: _exec_sbfx,

        # Saturation
        Op.SSAT: _exec_ssat,
        Op.USAT: _exec_usat,

        # System
        Op.MSR: _exec_msr,
        Op.MRS: _exec_mrs,
        Op.SVC: _exec_svc,
        Op.BKPT: _exec_bkpt,
        Op.CPSIE: _exec_cpsie,
        Op.CPSID: _exec_cpsid,

        # Exclusive
        Op.LDREX: _exec_ldrex,
        Op.LDREXB: _exec_ldrexb,
        Op.LDREXH: _exec_ldrexh,
        Op.STREX: _exec_strex,
        Op.STREXB: _exec_strexb,
        Op.STREXH: _exec_strexh,
        Op.CLREX: _exec_clrex,

        # Hints / Barriers
        Op.NOP: _exec_nop,
        Op.WFI: _exec_wfi,
        Op.WFE: _exec_wfe,
        Op.DMB: _exec_dmb,
        Op.DSB: _exec_dsb,
        Op.ISB: _exec_isb,
        Op.YIELD: _exec_yield,
        Op.SEV: _exec_sev,

        # Unknown
        Op.UNKNOWN: _exec_unknown,
        Op.UNDEFINED: _exec_undefined,
    }
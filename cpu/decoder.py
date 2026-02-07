"""
ARM Cortex-M7 Instruction Decoder (Thumb / Thumb-2)

Декодирует 16-битные Thumb и 32-битные Thumb-2 инструкции
в унифицированные объекты Instruction для исполнения.

Cortex-M7 поддерживает ARMv7E-M (Thumb + Thumb-2 + DSP extensions).
"""

from enum import Enum, auto
from cpu.alu import (
    SHIFT_LSL, SHIFT_LSR, SHIFT_ASR, SHIFT_ROR,
    sign_extend
)


class Op(Enum):
    """Все поддерживаемые операции."""
    # Неизвестная / нереализованная
    UNKNOWN = auto()
    NOP = auto()
    UNDEFINED = auto()

    # Data processing — register
    MOV = auto()
    MOVS = auto()
    MVN = auto()
    MVNS = auto()
    ADD = auto()
    ADDS = auto()
    ADC = auto()
    ADCS = auto()
    SUB = auto()
    SUBS = auto()
    SBC = auto()
    SBCS = auto()
    RSB = auto()
    RSBS = auto()
    MUL = auto()
    MULS = auto()
    AND = auto()
    ANDS = auto()
    ORR = auto()
    ORRS = auto()
    EOR = auto()
    EORS = auto()
    ORN = auto()
    ORNS = auto()
    BIC = auto()
    BICS = auto()
    TST = auto()
    TEQ = auto()
    CMP = auto()
    CMN = auto()
    NEG = auto()

    # Shifts
    LSL = auto()
    LSLS = auto()
    LSR = auto()
    LSRS = auto()
    ASR = auto()
    ASRS = auto()
    ROR = auto()
    RORS = auto()
    RRX = auto()
    RRXS = auto()

    # Multiply long / divide
    MLA = auto()
    MLS = auto()
    SMULL = auto()
    UMULL = auto()
    SMLAL = auto()
    UMLAL = auto()
    SDIV = auto()
    UDIV = auto()

    # Load/Store
    LDR = auto()
    LDRB = auto()
    LDRH = auto()
    LDRSB = auto()
    LDRSH = auto()
    LDRD = auto()
    LDM = auto()
    LDMDB = auto()
    LDR_LIT = auto()   # LDR from literal pool (PC-relative)

    STR = auto()
    STRB = auto()
    STRH = auto()
    STRD = auto()
    STM = auto()
    STMDB = auto()

    PUSH = auto()
    POP = auto()

    # Branch
    B = auto()
    BL = auto()
    BX = auto()
    BLX = auto()
    CBZ = auto()
    CBNZ = auto()
    TBB = auto()
    TBH = auto()

    # IT block
    IT = auto()

    # Extend
    SXTB = auto()
    SXTH = auto()
    UXTB = auto()
    UXTH = auto()
    SXTAB = auto()
    SXTAH = auto()
    UXTAB = auto()
    UXTAH = auto()

    # Bit manipulation
    CLZ = auto()
    RBIT = auto()
    REV = auto()
    REV16 = auto()
    REVSH = auto()
    BFI = auto()
    BFC = auto()
    UBFX = auto()
    SBFX = auto()

    # Saturation
    SSAT = auto()
    USAT = auto()

    # Move immediate
    MOVW = auto()
    MOVT = auto()

    # Hints / System
    SEV = auto()
    WFE = auto()
    WFI = auto()
    YIELD = auto()
    ISB = auto()
    DSB = auto()
    DMB = auto()

    # System
    MSR = auto()
    MRS = auto()
    SVC = auto()
    BKPT = auto()
    CPSIE = auto()
    CPSID = auto()

    # Exclusive access
    LDREX = auto()
    LDREXB = auto()
    LDREXH = auto()
    STREX = auto()
    STREXB = auto()
    STREXH = auto()
    CLREX = auto()


class Condition(Enum):
    """Условия выполнения (для условных переходов и IT блоков)."""
    EQ = 0   # Z==1
    NE = 1   # Z==0
    CS = 2   # C==1 (HS)
    CC = 3   # C==0 (LO)
    MI = 4   # N==1
    PL = 5   # N==0
    VS = 6   # V==1
    VC = 7   # V==0
    HI = 8   # C==1 and Z==0
    LS = 9   # C==0 or Z==1
    GE = 10  # N==V
    LT = 11  # N!=V
    GT = 12  # Z==0 and N==V
    LE = 13  # Z==1 or N!=V
    AL = 14  # Always
    NONE = 15


class Instruction:
    """Декодированная инструкция."""

    __slots__ = [
        'op',           # Op enum
        'cond',         # Condition enum
        'size',         # 2 или 4 байта
        'rd', 'rn', 'rm', 'rs', 'rt', 'rt2',  # Регистры (None если не используется)
        'rdlo', 'rdhi', # Для SMULL/UMULL
        'imm',          # Immediate значение
        'shift_type',   # Тип сдвига (0-3)
        'shift_n',      # Величина сдвига
        'setflags',     # Обновлять ли флаги
        'wback',        # Writeback (для load/store)
        'index',        # Pre/Post indexing
        'add',          # Добавлять или вычитать offset
        'register_list',# Для LDM/STM/PUSH/POP
        'raw',          # Сырые байты инструкции
        'address',      # Адрес инструкции
        'firstcond',    # Для IT: первое условие
        'mask',         # Для IT: маска
        'lsb',          # Для BFI/BFC/UBFX/SBFX
        'width',        # Для BFI/BFC/UBFX/SBFX
        'sat_imm',      # Для SSAT/USAT
        'sysreg',       # Для MSR/MRS — имя системного регистра
        'rotation',     # Для SXTB/UXTH и т.д.
    ]

    def __init__(self):
        self.op = Op.UNKNOWN
        self.cond = Condition.AL
        self.size = 2
        self.rd = None
        self.rn = None
        self.rm = None
        self.rs = None
        self.rt = None
        self.rt2 = None
        self.rdlo = None
        self.rdhi = None
        self.imm = None
        self.shift_type = SHIFT_LSL
        self.shift_n = 0
        self.setflags = False
        self.wback = False
        self.index = True
        self.add = True
        self.register_list = None
        self.raw = 0
        self.address = 0
        self.firstcond = 0
        self.mask = 0
        self.lsb = 0
        self.width = 0
        self.sat_imm = 0
        self.sysreg = None
        self.rotation = 0

    def __repr__(self):
        parts = [f"{self.op.name}"]
        if self.cond != Condition.AL:
            parts[0] += f".{self.cond.name}"
        if self.rd is not None:
            parts.append(f"Rd=R{self.rd}")
        if self.rt is not None:
            parts.append(f"Rt=R{self.rt}")
        if self.rn is not None:
            parts.append(f"Rn=R{self.rn}")
        if self.rm is not None:
            parts.append(f"Rm=R{self.rm}")
        if self.imm is not None:
            parts.append(f"imm=0x{self.imm:X}")
        if self.register_list:
            parts.append(f"regs={self.register_list}")
        return f"Inst(0x{self.address:08X}: {' '.join(parts)}, size={self.size})"


class Decoder:
    """
    Декодер инструкций Thumb / Thumb-2.
    """

    def __init__(self):
        pass

    def decode(self, hw1, hw2, address):
        """
        Декодировать инструкцию.

        hw1: первое 16-битное полуслово
        hw2: второе 16-битное полуслово (для 32-бит инструкций, иначе 0)
        address: адрес инструкции

        Возвращает Instruction.
        """
        inst = Instruction()
        inst.address = address

        # Определить 16 или 32-бит инструкция
        if self._is_thumb32(hw1):
            inst.size = 4
            inst.raw = (hw1 << 16) | hw2
            self._decode_thumb32(hw1, hw2, inst)
        else:
            inst.size = 2
            inst.raw = hw1
            self._decode_thumb16(hw1, inst)

        return inst

    @staticmethod
    def _is_thumb32(hw1):
        """
        Thumb-2 32-бит инструкции начинаются с:
        0b11101... 0b11110... 0b11111...
        т.е. верхние 5 бит >= 0b11101
        """
        top5 = (hw1 >> 11) & 0x1F
        return top5 >= 0x1D

    # ===============================================================
    # 16-bit Thumb
    # ===============================================================

    def _decode_thumb16(self, hw, inst):
        """Декодировать 16-битную Thumb инструкцию."""
        top8 = (hw >> 8) & 0xFF
        top6 = (hw >> 10) & 0x3F
        top5 = (hw >> 11) & 0x1F
        opcode = (hw >> 6) & 0xF

        # ==== Shift (immediate), Add, Sub, Mov, Compare ====
        if top5 <= 0x03:
            # LSL imm: 000 00 imm5 Rm Rd
            self._decode_shift_imm(hw, inst, SHIFT_LSL)
        elif top5 <= 0x05:
            # LSR imm
            if top5 == 0x04:
                self._decode_shift_imm(hw, inst, SHIFT_LSR)
            else:
                self._decode_shift_imm(hw, inst, SHIFT_ASR)
        elif top5 == 0x06:
            # ASR imm
            self._decode_shift_imm(hw, inst, SHIFT_ASR)
        elif top6 == 0x06:
            # 000110 — ADD reg (3 regs): 0001100 Rm Rn Rd
            self._decode_add_sub_reg(hw, inst)
        elif top6 == 0x07:
            # 000111 — SUB reg
            self._decode_add_sub_reg(hw, inst)

        # Переделаем более структурированно
        # Сброс и начнём заново

        op_top = (hw >> 13) & 0x7

        if op_top == 0b000:
            self._decode_thumb16_shift_add_sub_mov_cmp(hw, inst)
        elif op_top == 0b001:
            self._decode_thumb16_data_imm(hw, inst)
        elif op_top == 0b010:
            sub_op = (hw >> 10) & 0x7
            if sub_op == 0b000:
                self._decode_thumb16_data_proc(hw, inst)
            elif sub_op == 0b001:
                self._decode_thumb16_special_branch(hw, inst)
            elif sub_op in (0b010, 0b011):
                self._decode_thumb16_ldr_literal(hw, inst)
            else:
                self._decode_thumb16_load_store(hw, inst)
        elif op_top == 0b011:
            self._decode_thumb16_load_store_imm(hw, inst)
        elif op_top == 0b100:
            if hw & (1 << 12):
                self._decode_thumb16_load_store_sp(hw, inst)
            else:
                self._decode_thumb16_load_store_halfword(hw, inst)
        elif op_top == 0b101:
            if hw & (1 << 12):
                self._decode_thumb16_misc(hw, inst)
            else:
                self._decode_thumb16_adr_add_sp(hw, inst)
        elif op_top == 0b110:
            if hw & (1 << 12):
                self._decode_thumb16_cond_branch_svc(hw, inst)
            else:
                self._decode_thumb16_ldm_stm(hw, inst)
        elif op_top == 0b111:
            self._decode_thumb16_uncond_branch(hw, inst)

    def _decode_thumb16_shift_add_sub_mov_cmp(self, hw, inst):
        """00000-00111: LSL/LSR/ASR imm, ADD/SUB reg/imm3."""
        op = (hw >> 11) & 0x3
        if op == 0b00:
            # LSL Rd, Rm, #imm5
            imm5 = (hw >> 6) & 0x1F
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            inst.op = Op.LSLS
            inst.setflags = True
            inst.rd = rd
            inst.rm = rm
            inst.imm = imm5
            inst.shift_type = SHIFT_LSL
            inst.shift_n = imm5
            if imm5 == 0:
                inst.op = Op.MOVS
        elif op == 0b01:
            # LSR Rd, Rm, #imm5
            imm5 = (hw >> 6) & 0x1F
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            inst.op = Op.LSRS
            inst.setflags = True
            inst.rd = rd
            inst.rm = rm
            inst.shift_type = SHIFT_LSR
            inst.shift_n = imm5 if imm5 else 32
        elif op == 0b10:
            # ASR Rd, Rm, #imm5
            imm5 = (hw >> 6) & 0x1F
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            inst.op = Op.ASRS
            inst.setflags = True
            inst.rd = rd
            inst.rm = rm
            inst.shift_type = SHIFT_ASR
            inst.shift_n = imm5 if imm5 else 32
        elif op == 0b11:
            sub_op = (hw >> 9) & 0x3
            if sub_op == 0b00:
                # ADD Rd, Rn, Rm
                rm = (hw >> 6) & 0x7
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                inst.op = Op.ADDS
                inst.setflags = True
                inst.rd = rd
                inst.rn = rn
                inst.rm = rm
            elif sub_op == 0b01:
                # SUB Rd, Rn, Rm
                rm = (hw >> 6) & 0x7
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                inst.op = Op.SUBS
                inst.setflags = True
                inst.rd = rd
                inst.rn = rn
                inst.rm = rm
            elif sub_op == 0b10:
                # ADD Rd, Rn, #imm3
                imm3 = (hw >> 6) & 0x7
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                inst.op = Op.ADDS
                inst.setflags = True
                inst.rd = rd
                inst.rn = rn
                inst.imm = imm3
            elif sub_op == 0b11:
                # SUB Rd, Rn, #imm3
                imm3 = (hw >> 6) & 0x7
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                inst.op = Op.SUBS
                inst.setflags = True
                inst.rd = rd
                inst.rn = rn
                inst.imm = imm3

    def _decode_thumb16_data_imm(self, hw, inst):
        """001xx: MOV/CMP/ADD/SUB Rd, #imm8."""
        op = (hw >> 11) & 0x3
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF

        if op == 0b00:
            inst.op = Op.MOVS
            inst.setflags = True
            inst.rd = rd
            inst.imm = imm8
        elif op == 0b01:
            inst.op = Op.CMP
            inst.rn = rd
            inst.imm = imm8
        elif op == 0b10:
            inst.op = Op.ADDS
            inst.setflags = True
            inst.rd = rd
            inst.rn = rd
            inst.imm = imm8
        elif op == 0b11:
            inst.op = Op.SUBS
            inst.setflags = True
            inst.rd = rd
            inst.rn = rd
            inst.imm = imm8

    def _decode_thumb16_data_proc(self, hw, inst):
        """010000xxxx: Data processing (register)."""
        op = (hw >> 6) & 0xF
        rm_rs = (hw >> 3) & 0x7
        rd_rn = hw & 0x7

        ops_map = {
            0x0: (Op.ANDS, True),
            0x1: (Op.EORS, True),
            0x2: (Op.LSLS, True),  # LSL by register
            0x3: (Op.LSRS, True),
            0x4: (Op.ASRS, True),
            0x5: (Op.ADCS, True),
            0x6: (Op.SBCS, True),
            0x7: (Op.RORS, True),
            0x8: (Op.TST, False),
            0x9: (Op.RSBS, True),   # NEG = RSB Rd, Rn, #0
            0xA: (Op.CMP, False),
            0xB: (Op.CMN, False),
            0xC: (Op.ORRS, True),
            0xD: (Op.MULS, True),
            0xE: (Op.BICS, True),
            0xF: (Op.MVNS, True),
        }

        mapped_op, has_rd = ops_map.get(op, (Op.UNKNOWN, False))
        inst.op = mapped_op
        inst.setflags = True

        if op in (0x2, 0x3, 0x4, 0x7):
            # Shift by register: Rd = Rd shift Rs
            inst.rd = rd_rn
            inst.rn = rd_rn
            inst.rs = rm_rs
        elif op == 0x9:
            # RSB Rd, Rm, #0 (NEG)
            inst.rd = rd_rn
            inst.rn = rm_rs
            inst.imm = 0
        elif op == 0xD:
            # MUL Rd, Rn, Rd
            inst.rd = rd_rn
            inst.rn = rd_rn
            inst.rm = rm_rs
        elif op in (0x8, 0xA, 0xB):
            # TST/CMP/CMN — no Rd
            inst.rn = rd_rn
            inst.rm = rm_rs
        else:
            inst.rd = rd_rn
            inst.rn = rd_rn
            inst.rm = rm_rs

    def _decode_thumb16_special_branch(self, hw, inst):
        """010001xx: Special data / Branch-exchange."""
        op = (hw >> 8) & 0x3

        if op == 0b00:
            # ADD Rd, Rm (high registers allowed)
            rd = ((hw >> 4) & 0x8) | (hw & 0x7)  # D:Rd
            rm = (hw >> 3) & 0xF
            inst.op = Op.ADD
            inst.rd = rd
            inst.rn = rd
            inst.rm = rm
        elif op == 0b01:
            # CMP Rn, Rm (high registers)
            rn = ((hw >> 4) & 0x8) | (hw & 0x7)
            rm = (hw >> 3) & 0xF
            inst.op = Op.CMP
            inst.rn = rn
            inst.rm = rm
        elif op == 0b10:
            # MOV Rd, Rm (high registers)
            rd = ((hw >> 4) & 0x8) | (hw & 0x7)
            rm = (hw >> 3) & 0xF
            inst.op = Op.MOV
            inst.rd = rd
            inst.rm = rm
        elif op == 0b11:
            # BX / BLX
            rm = (hw >> 3) & 0xF
            link = bool(hw & (1 << 7))
            if link:
                inst.op = Op.BLX
            else:
                inst.op = Op.BX
            inst.rm = rm

    def _decode_thumb16_ldr_literal(self, hw, inst):
        """01001: LDR Rt, [PC, #imm8*4]."""
        rt = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        inst.op = Op.LDR_LIT
        inst.rt = rt
        inst.imm = imm8 * 4
        inst.rn = 15  # PC

    def _decode_thumb16_load_store(self, hw, inst):
        """0101xxx: Load/Store register offset."""
        opA = (hw >> 9) & 0x7
        rm = (hw >> 6) & 0x7
        rn = (hw >> 3) & 0x7
        rt = hw & 0x7

        inst.rt = rt
        inst.rn = rn
        inst.rm = rm
        inst.index = True
        inst.add = True

        ops = {
            0b000: Op.STR,
            0b001: Op.STRH,
            0b010: Op.STRB,
            0b011: Op.LDRSB,
            0b100: Op.LDR,
            0b101: Op.LDRH,
            0b110: Op.LDRB,
            0b111: Op.LDRSH,
        }
        inst.op = ops.get(opA, Op.UNKNOWN)

    def _decode_thumb16_load_store_imm(self, hw, inst):
        """011xx: LDR/STR (imm5), byte/word."""
        op = (hw >> 11) & 0x3
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 0x7
        rt = hw & 0x7

        inst.rt = rt
        inst.rn = rn
        inst.index = True
        inst.add = True

        if op == 0b00:
            inst.op = Op.STR
            inst.imm = imm5 * 4
        elif op == 0b01:
            inst.op = Op.LDR
            inst.imm = imm5 * 4
        elif op == 0b10:
            inst.op = Op.STRB
            inst.imm = imm5
        elif op == 0b11:
            inst.op = Op.LDRB
            inst.imm = imm5

    def _decode_thumb16_load_store_halfword(self, hw, inst):
        """1000x: LDRH/STRH (imm5)."""
        is_load = bool(hw & (1 << 11))
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 0x7
        rt = hw & 0x7

        inst.op = Op.LDRH if is_load else Op.STRH
        inst.rt = rt
        inst.rn = rn
        inst.imm = imm5 * 2
        inst.index = True
        inst.add = True

    def _decode_thumb16_load_store_sp(self, hw, inst):
        """1001x: LDR/STR Rt, [SP, #imm8*4]."""
        is_load = bool(hw & (1 << 11))
        rt = (hw >> 8) & 0x7
        imm8 = hw & 0xFF

        inst.op = Op.LDR if is_load else Op.STR
        inst.rt = rt
        inst.rn = 13  # SP
        inst.imm = imm8 * 4
        inst.index = True
        inst.add = True

    def _decode_thumb16_adr_add_sp(self, hw, inst):
        """1010x: ADR / ADD Rd, SP, #imm8*4."""
        is_sp = bool(hw & (1 << 11))
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF

        inst.op = Op.ADD
        inst.rd = rd
        inst.imm = imm8 * 4
        if is_sp:
            inst.rn = 13  # SP
        else:
            inst.rn = 15  # PC (ADR)

    def _decode_thumb16_misc(self, hw, inst):
        """1011xxxx: Misc 16-bit instructions."""
        sub_op = (hw >> 8) & 0xF

        if sub_op == 0b0000:
            # ADD SP, #imm7*4 / SUB SP, #imm7*4
            if hw & (1 << 7):
                inst.op = Op.SUB
            else:
                inst.op = Op.ADD
            inst.rd = 13
            inst.rn = 13
            inst.imm = (hw & 0x7F) * 4

        elif sub_op in (0b0001, 0b0011):
            # SXTH, SXTB, UXTH, UXTB
            op2 = (hw >> 6) & 0x3
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            ext_ops = {0: Op.SXTH, 1: Op.SXTB, 2: Op.UXTH, 3: Op.UXTB}
            inst.op = ext_ops.get(op2, Op.UNKNOWN)
            inst.rd = rd
            inst.rm = rm

        elif sub_op in (0b0010,):
            # SXTH/SXTB/UXTH/UXTB (same encoding range)
            op2 = (hw >> 6) & 0x3
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            ext_ops = {0: Op.SXTH, 1: Op.SXTB, 2: Op.UXTH, 3: Op.UXTB}
            inst.op = ext_ops.get(op2, Op.UNKNOWN)
            inst.rd = rd
            inst.rm = rm

        elif sub_op in (0b0100, 0b0101):
            # PUSH {reg_list} (optionally LR)
            inst.op = Op.PUSH
            reg_list = hw & 0xFF
            registers = []
            for i in range(8):
                if reg_list & (1 << i):
                    registers.append(i)
            if hw & (1 << 8):  # M bit = LR
                registers.append(14)
            inst.register_list = registers

        elif sub_op == 0b0110:
            # CPS
            if hw & (1 << 4):
                inst.op = Op.CPSID
            else:
                inst.op = Op.CPSIE
            inst.imm = hw & 0x7  # affect flags: a, i, f

        elif sub_op in (0b1001, 0b1011):
            # REV, REV16, REVSH
            op2 = (hw >> 6) & 0x3
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            rev_ops = {0: Op.REV, 1: Op.REV16, 3: Op.REVSH}
            inst.op = rev_ops.get(op2, Op.UNKNOWN)
            inst.rd = rd
            inst.rm = rm

        elif sub_op in (0b1100, 0b1101):
            # POP {reg_list} (optionally PC)
            inst.op = Op.POP
            reg_list = hw & 0xFF
            registers = []
            for i in range(8):
                if reg_list & (1 << i):
                    registers.append(i)
            if hw & (1 << 8):  # P bit = PC
                registers.append(15)
            inst.register_list = registers

        elif sub_op == 0b1110:
            # BKPT
            inst.op = Op.BKPT
            inst.imm = hw & 0xFF

        elif sub_op == 0b1111:
            # IT and hints
            if hw & 0xF:
                # IT
                inst.op = Op.IT
                inst.firstcond = (hw >> 4) & 0xF
                inst.mask = hw & 0xF
                inst.cond = Condition(inst.firstcond)
            else:
                # Hints
                hint_op = (hw >> 4) & 0xF
                hint_map = {0: Op.NOP, 1: Op.YIELD, 2: Op.WFE, 3: Op.WFI, 4: Op.SEV}
                inst.op = hint_map.get(hint_op, Op.NOP)

        elif sub_op in (0b1010,):
            # CBZ / CBNZ (part 2, bit[11]=1)
            pass  # handled below

        # CBZ/CBNZ: 1011 x0x1
        if (sub_op & 0b0101) == 0b0001 and (sub_op & 0b1000) == 0:
            # CBZ
            rn = hw & 0x7
            i = (hw >> 9) & 1
            imm5 = (hw >> 3) & 0x1F
            imm = (i << 5) | imm5
            inst.op = Op.CBZ
            inst.rn = rn
            inst.imm = imm * 2
        elif (sub_op & 0b0101) == 0b0001 and (sub_op & 0b1000):
            # CBNZ
            rn = hw & 0x7
            i = (hw >> 9) & 1
            imm5 = (hw >> 3) & 0x1F
            imm = (i << 5) | imm5
            inst.op = Op.CBNZ
            inst.rn = rn
            inst.imm = imm * 2

    def _decode_thumb16_ldm_stm(self, hw, inst):
        """1100x: LDM/STM."""
        is_load = bool(hw & (1 << 11))
        rn = (hw >> 8) & 0x7
        reg_list = hw & 0xFF

        registers = []
        for i in range(8):
            if reg_list & (1 << i):
                registers.append(i)

        if is_load:
            inst.op = Op.LDM
        else:
            inst.op = Op.STM

        inst.rn = rn
        inst.register_list = registers
        # Writeback: для STM всегда, для LDM если Rn не в списке
        inst.wback = True
        if is_load and rn in registers:
            inst.wback = False

    def _decode_thumb16_cond_branch_svc(self, hw, inst):
        """1101xxxx: Conditional branch / SVC."""
        cond = (hw >> 8) & 0xF

        if cond == 0xE:
            inst.op = Op.UNDEFINED
            return
        if cond == 0xF:
            inst.op = Op.SVC
            inst.imm = hw & 0xFF
            return

        # Conditional branch
        imm8 = hw & 0xFF
        offset = sign_extend(imm8 << 1, 9)
        inst.op = Op.B
        inst.cond = Condition(cond)
        inst.imm = offset

    def _decode_thumb16_uncond_branch(self, hw, inst):
        """11100: Unconditional branch."""
        imm11 = hw & 0x7FF
        offset = sign_extend(imm11 << 1, 12)
        inst.op = Op.B
        inst.imm = offset

    # ===============================================================
    # Вспомогательные для 16-bit
    # ===============================================================

    def _decode_shift_imm(self, hw, inst, shift_type):
        """Общая декодировка для сдвигов с immediate."""
        imm5 = (hw >> 6) & 0x1F
        rm = (hw >> 3) & 0x7
        rd = hw & 0x7
        inst.rd = rd
        inst.rm = rm
        inst.shift_type = shift_type
        inst.shift_n = imm5
        inst.setflags = True

    def _decode_add_sub_reg(self, hw, inst):
        """ADD/SUB register (3 reg)."""
        rm = (hw >> 6) & 0x7
        rn = (hw >> 3) & 0x7
        rd = hw & 0x7
        is_sub = bool(hw & (1 << 9))
        inst.op = Op.SUBS if is_sub else Op.ADDS
        inst.setflags = True
        inst.rd = rd
        inst.rn = rn
        inst.rm = rm

    # ===============================================================
    # 32-bit Thumb-2
    # ===============================================================

    def _decode_thumb32(self, hw1, hw2, inst):
        """Декодировать 32-битную Thumb-2 инструкцию."""
        op1 = (hw1 >> 11) & 0x3  # биты [12:11] первого полуслова
        op2 = (hw1 >> 4) & 0x7F  # биты [10:4] первого полуслова
        op = (hw2 >> 15) & 0x1   # бит [15] второго полуслова

        if op1 == 0b01:
            if (op2 & 0x64) == 0x00:
                self._decode_t32_load_store_multiple(hw1, hw2, inst)
            elif (op2 & 0x64) == 0x04:
                self._decode_t32_load_store_dual(hw1, hw2, inst)
            elif (op2 & 0x60) == 0x20:
                self._decode_t32_data_proc_shifted_reg(hw1, hw2, inst)
            elif (op2 & 0x40) == 0x40:
                self._decode_t32_coprocessor(hw1, hw2, inst)
        elif op1 == 0b10:
            if op == 0:
                if (op2 & 0x20) == 0:
                    self._decode_t32_data_proc_modified_imm(hw1, hw2, inst)
                else:
                    self._decode_t32_data_proc_plain_imm(hw1, hw2, inst)
            else:
                self._decode_t32_branch_misc(hw1, hw2, inst)
        elif op1 == 0b11:
            if (op2 & 0x71) == 0x00:
                self._decode_t32_store_single(hw1, hw2, inst)
            elif (op2 & 0x67) == 0x01:
                self._decode_t32_load_byte(hw1, hw2, inst)
            elif (op2 & 0x67) == 0x03:
                self._decode_t32_load_halfword(hw1, hw2, inst)
            elif (op2 & 0x67) == 0x05:
                self._decode_t32_load_word(hw1, hw2, inst)
            elif (op2 & 0x67) == 0x07:
                self._decode_t32_undefined(hw1, hw2, inst)
            elif (op2 & 0x70) == 0x10:
                self._decode_t32_store_single(hw1, hw2, inst)
            elif (op2 & 0x70) == 0x20:
                self._decode_t32_data_proc_reg(hw1, hw2, inst)
            elif (op2 & 0x78) == 0x30:
                self._decode_t32_multiply(hw1, hw2, inst)
            elif (op2 & 0x78) == 0x38:
                self._decode_t32_long_multiply(hw1, hw2, inst)
            elif (op2 & 0x40) == 0x40:
                self._decode_t32_coprocessor(hw1, hw2, inst)
            else:
                self._decode_t32_load_word(hw1, hw2, inst)

    # ---------------------------------------------------------------
    # 32-bit: Load/Store Multiple
    # ---------------------------------------------------------------

    def _decode_t32_load_store_multiple(self, hw1, hw2, inst):
        op = (hw1 >> 7) & 0x3
        is_load = bool(hw1 & (1 << 4))
        w = bool(hw1 & (1 << 5))
        rn = hw1 & 0xF
        reg_list = hw2 & 0x1FFF  # bits [12:0], бит 13=reserved

        registers = []
        for i in range(16):
            if hw2 & (1 << i):
                registers.append(i)

        inst.rn = rn
        inst.register_list = registers
        inst.wback = w

        if op == 0b01:
            if is_load:
                inst.op = Op.LDM
            else:
                inst.op = Op.STM
        elif op == 0b10:
            if is_load:
                inst.op = Op.LDMDB
            else:
                inst.op = Op.STMDB

    # ---------------------------------------------------------------
    # 32-bit: Load/Store Dual, Exclusive, Table Branch
    # ---------------------------------------------------------------

    def _decode_t32_load_store_dual(self, hw1, hw2, inst):
        op1 = (hw1 >> 7) & 0x3
        op2_bits = (hw1 >> 4) & 0x7
        op3 = (hw2 >> 4) & 0xF
        rn = hw1 & 0xF

        # LDRD / STRD
        p = bool(hw1 & (1 << 8))
        u = bool(hw1 & (1 << 7))
        w = bool(hw1 & (1 << 5))
        is_load = bool(hw1 & (1 << 4))

        rt = (hw2 >> 12) & 0xF
        rt2 = (hw2 >> 8) & 0xF
        imm8 = hw2 & 0xFF

        # Check for TBB/TBH
        if rn == 0xF and not is_load:
            # Could be something else
            pass

        if (op1 & 0x2) or p or w:
            if is_load:
                # Check for LDREX variants
                if op2_bits == 0x4 and not p and u and not w:
                    # LDREX
                    inst.op = Op.LDREX
                    inst.rt = rt
                    inst.rn = rn
                    inst.imm = imm8 * 4
                    return
                if op2_bits == 0x5:
                    if op3 == 0x0:
                        inst.op = Op.TBB
                        inst.rn = rn
                        inst.rm = hw2 & 0xF
                        return
                    elif op3 == 0x1:
                        inst.op = Op.TBH
                        inst.rn = rn
                        inst.rm = hw2 & 0xF
                        return
                    elif op3 == 0x4:
                        inst.op = Op.LDREXB
                        inst.rt = rt
                        inst.rn = rn
                        return
                    elif op3 == 0x5:
                        inst.op = Op.LDREXH
                        inst.rt = rt
                        inst.rn = rn
                        return

                inst.op = Op.LDRD
                inst.rt = rt
                inst.rt2 = rt2
                inst.rn = rn
                inst.imm = imm8 * 4
                inst.index = p
                inst.add = u
                inst.wback = w
            else:
                # STREX variants
                if op2_bits == 0x4 and not p and u and not w:
                    inst.op = Op.STREX
                    inst.rd = (hw2 >> 8) & 0xF
                    inst.rt = (hw2 >> 12) & 0xF
                    inst.rn = rn
                    inst.imm = imm8 * 4
                    return
                if op2_bits == 0x5 and op3 == 0x4:
                    inst.op = Op.STREXB
                    inst.rd = hw2 & 0xF
                    inst.rt = rt
                    inst.rn = rn
                    return
                if op2_bits == 0x5 and op3 == 0x5:
                    inst.op = Op.STREXH
                    inst.rd = hw2 & 0xF
                    inst.rt = rt
                    inst.rn = rn
                    return

                inst.op = Op.STRD
                inst.rt = rt
                inst.rt2 = rt2
                inst.rn = rn
                inst.imm = imm8 * 4
                inst.index = p
                inst.add = u
                inst.wback = w

    # ---------------------------------------------------------------
    # 32-bit: Data Processing (Shifted Register)
    # ---------------------------------------------------------------

    def _decode_t32_data_proc_shifted_reg(self, hw1, hw2, inst):
        op = (hw1 >> 5) & 0xF
        rn = hw1 & 0xF
        s = bool(hw1 & (1 << 4))
        rd = (hw2 >> 8) & 0xF
        rm = hw2 & 0xF

        # Decode shift
        imm3 = (hw2 >> 12) & 0x7
        imm2 = (hw2 >> 6) & 0x3
        stype = (hw2 >> 4) & 0x3
        shift_n = (imm3 << 2) | imm2

        inst.rd = rd
        inst.rn = rn
        inst.rm = rm
        inst.setflags = s
        inst.shift_type = stype
        inst.shift_n = shift_n

        op_map = {
            0x0: (Op.ANDS if s else Op.AND, True),   # AND / TST (if Rd==15)
            0x1: (Op.BICS if s else Op.BIC, True),
            0x2: (Op.ORRS if s else Op.ORR, True),   # ORR / MOV (if Rn==15)
            0x3: (Op.ORNS if s else Op.ORN, True),   # ORN / MVN (if Rn==15)
            0x4: (Op.EORS if s else Op.EOR, True),   # EOR / TEQ (if Rd==15)
            0x6: (Op.ADDS if s else Op.ADD, True),    # PKH if S==0?
            0x8: (Op.ADDS if s else Op.ADD, True),    # ADD / CMN (if Rd==15)
            0xA: (Op.ADCS if s else Op.ADC, True),
            0xB: (Op.SBCS if s else Op.SBC, True),
            0xD: (Op.SUBS if s else Op.SUB, True),    # SUB / CMP (if Rd==15)
            0xE: (Op.RSBS if s else Op.RSB, True),
        }

        if op in op_map:
            mapped, _ = op_map[op]
            inst.op = mapped

            # Special cases
            if op == 0x0 and rd == 15 and s:
                inst.op = Op.TST
                inst.rd = None
            elif op == 0x4 and rd == 15 and s:
                inst.op = Op.TEQ
                inst.rd = None
            elif op == 0x8 and rd == 15 and s:
                inst.op = Op.CMN
                inst.rd = None
            elif op == 0xD and rd == 15 and s:
                inst.op = Op.CMP
                inst.rd = None
            elif op == 0x2 and rn == 15:
                inst.op = Op.MOVS if s else Op.MOV
                inst.rn = None
            elif op == 0x3 and rn == 15:
                inst.op = Op.MVNS if s else Op.MVN
                inst.rn = None
        else:
            inst.op = Op.UNKNOWN

    # ---------------------------------------------------------------
    # 32-bit: Data Processing (Modified Immediate)
    # ---------------------------------------------------------------

    def _decode_t32_data_proc_modified_imm(self, hw1, hw2, inst):
        op = (hw1 >> 5) & 0xF
        rn = hw1 & 0xF
        s = bool(hw1 & (1 << 4))
        rd = (hw2 >> 8) & 0xF

        # Construct imm12 from i:imm3:imm8
        i = (hw1 >> 10) & 0x1
        imm3 = (hw2 >> 12) & 0x7
        imm8 = hw2 & 0xFF
        imm12 = (i << 11) | (imm3 << 8) | imm8

        inst.rd = rd
        inst.rn = rn
        inst.setflags = s
        inst.imm = imm12  # Will be expanded by executor using thumb_expand_imm

        op_map = {
            0x0: Op.ANDS if s else Op.AND,
            0x1: Op.BICS if s else Op.BIC,
            0x2: Op.ORRS if s else Op.ORR,
            0x3: Op.ORNS if s else Op.ORN,
            0x4: Op.EORS if s else Op.EOR,
            0x8: Op.ADDS if s else Op.ADD,
            0xA: Op.ADCS if s else Op.ADC,
            0xB: Op.SBCS if s else Op.SBC,
            0xD: Op.SUBS if s else Op.SUB,
            0xE: Op.RSBS if s else Op.RSB,
        }

        if op in op_map:
            inst.op = op_map[op]
            # Special cases
            if op == 0x0 and rd == 15 and s:
                inst.op = Op.TST
                inst.rd = None
            elif op == 0x4 and rd == 15 and s:
                inst.op = Op.TEQ
                inst.rd = None
            elif op == 0x8 and rd == 15 and s:
                inst.op = Op.CMN
                inst.rd = None
            elif op == 0xD and rd == 15 and s:
                inst.op = Op.CMP
                inst.rd = None
            elif op == 0x2 and rn == 15:
                inst.op = Op.MOVS if s else Op.MOV
            elif op == 0x3 and rn == 15:
                inst.op = Op.MVNS if s else Op.MVN
        else:
            inst.op = Op.UNKNOWN

    # ---------------------------------------------------------------
    # 32-bit: Data Processing (Plain Binary Immediate)
    # ---------------------------------------------------------------

    def _decode_t32_data_proc_plain_imm(self, hw1, hw2, inst):
        op = (hw1 >> 4) & 0x1F
        rn = hw1 & 0xF
        rd = (hw2 >> 8) & 0xF

        if op == 0x00:
            if rn == 15:
                # ADR (add variant)
                inst.op = Op.ADD
                inst.rd = rd
                inst.rn = 15
            else:
                # ADDW Rd, Rn, #imm12
                inst.op = Op.ADD
                inst.rd = rd
                inst.rn = rn
            i = (hw1 >> 10) & 1
            imm3 = (hw2 >> 12) & 0x7
            imm8 = hw2 & 0xFF
            inst.imm = (i << 11) | (imm3 << 8) | imm8
        elif op == 0x04:
            # MOVW Rd, #imm16
            imm4 = hw1 & 0xF
            i = (hw1 >> 10) & 1
            imm3 = (hw2 >> 12) & 0x7
            imm8 = hw2 & 0xFF
            inst.op = Op.MOVW
            inst.rd = rd
            inst.imm = (imm4 << 12) | (i << 11) | (imm3 << 8) | imm8
        elif op == 0x0A:
            if rn == 15:
                # ADR (sub variant)
                inst.op = Op.SUB
                inst.rd = rd
                inst.rn = 15
            else:
                # SUBW Rd, Rn, #imm12
                inst.op = Op.SUB
                inst.rd = rd
                inst.rn = rn
            i = (hw1 >> 10) & 1
            imm3 = (hw2 >> 12) & 0x7
            imm8 = hw2 & 0xFF
            inst.imm = (i << 11) | (imm3 << 8) | imm8
        elif op == 0x0C:
            # MOVT Rd, #imm16
            imm4 = hw1 & 0xF
            i = (hw1 >> 10) & 1
            imm3 = (hw2 >> 12) & 0x7
            imm8 = hw2 & 0xFF
            inst.op = Op.MOVT
            inst.rd = rd
            inst.imm = (imm4 << 12) | (i << 11) | (imm3 << 8) | imm8
        elif op == 0x10:
            # SSAT
            inst.op = Op.SSAT
            inst.rd = rd
            inst.rn = rn
            inst.sat_imm = (hw2 & 0x1F) + 1
            sh = (hw1 >> 5) & 1
            imm3 = (hw2 >> 12) & 0x7
            imm2 = (hw2 >> 6) & 0x3
            inst.shift_type = SHIFT_ASR if sh else SHIFT_LSL
            inst.shift_n = (imm3 << 2) | imm2
        elif op == 0x18:
            # USAT
            inst.op = Op.USAT
            inst.rd = rd
            inst.rn = rn
            inst.sat_imm = hw2 & 0x1F
            sh = (hw1 >> 5) & 1
            imm3 = (hw2 >> 12) & 0x7
            imm2 = (hw2 >> 6) & 0x3
            inst.shift_type = SHIFT_ASR if sh else SHIFT_LSL
            inst.shift_n = (imm3 << 2) | imm2
        elif op in (0x16, 0x14):
            # BFI / BFC
            imm3 = (hw2 >> 12) & 0x7
            imm2 = (hw2 >> 6) & 0x3
            msb = hw2 & 0x1F
            lsb_val = (imm3 << 2) | imm2
            width_val = msb - lsb_val + 1
            if rn == 15:
                inst.op = Op.BFC
            else:
                inst.op = Op.BFI
                inst.rn = rn
            inst.rd = rd
            inst.lsb = lsb_val
            inst.width = width_val
        elif op in (0x1C, 0x1A):
            # UBFX / SBFX
            imm3 = (hw2 >> 12) & 0x7
            imm2 = (hw2 >> 6) & 0x3
            widthm1 = hw2 & 0x1F
            inst.rn = rn
            inst.rd = rd
            inst.lsb = (imm3 << 2) | imm2
            inst.width = widthm1 + 1
            inst.op = Op.UBFX if op == 0x1C else Op.SBFX
        else:
            inst.op = Op.UNKNOWN

    # ---------------------------------------------------------------
    # 32-bit: Branch and Miscellaneous Control
    # ---------------------------------------------------------------

    def _decode_t32_branch_misc(self, hw1, hw2, inst):
        op1 = (hw1 >> 4) & 0x7F
        op2_val = (hw2 >> 12) & 0x7

        if (op2_val & 0x5) == 0x0:
            # Conditional branch or misc
            if (op1 & 0x38) != 0x38:
                # Conditional branch B<cond>
                cond = (hw1 >> 6) & 0xF
                s = (hw1 >> 10) & 1
                imm6 = hw1 & 0x3F
                j1 = (hw2 >> 13) & 1
                j2 = (hw2 >> 11) & 1
                imm11 = hw2 & 0x7FF
                imm = (s << 20) | (j2 << 19) | (j1 << 18) | (imm6 << 12) | (imm11 << 1)
                imm = sign_extend(imm, 21)
                inst.op = Op.B
                inst.cond = Condition(cond)
                inst.imm = imm
            else:
                # Misc control: MSR, MRS, hints, etc
                self._decode_t32_misc_control(hw1, hw2, inst)
        elif (op2_val & 0x5) == 0x1:
            # B (unconditional)
            s = (hw1 >> 10) & 1
            imm10 = hw1 & 0x3FF
            j1 = (hw2 >> 13) & 1
            j2 = (hw2 >> 11) & 1
            imm11 = hw2 & 0x7FF
            i1 = ~(j1 ^ s) & 1
            i2 = ~(j2 ^ s) & 1
            imm = (s << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
            imm = sign_extend(imm, 25)
            inst.op = Op.B
            inst.imm = imm
        elif (op2_val & 0x5) == 0x4:
            # BLX (to ARM — not used in Cortex-M but decode anyway)
            inst.op = Op.UNKNOWN
        elif (op2_val & 0x5) == 0x5:
            # BL
            s = (hw1 >> 10) & 1
            imm10 = hw1 & 0x3FF
            j1 = (hw2 >> 13) & 1
            j2 = (hw2 >> 11) & 1
            imm11 = hw2 & 0x7FF
            i1 = ~(j1 ^ s) & 1
            i2 = ~(j2 ^ s) & 1
            imm = (s << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
            imm = sign_extend(imm, 25)
            inst.op = Op.BL
            inst.imm = imm

    def _decode_t32_misc_control(self, hw1, hw2, inst):
        """Decode misc control instructions within branch encoding."""
        op = (hw1 >> 4) & 0x7F

        if (op & 0x7B) == 0x38:
            # MSR
            rn = hw1 & 0xF
            sysm = hw2 & 0xFF
            inst.op = Op.MSR
            inst.rn = rn
            inst.imm = sysm
            self._decode_sysreg(inst, sysm, is_write=True)
        elif (op & 0x7B) == 0x3B:
            # Misc control
            op2_misc = (hw2 >> 4) & 0xF
            if op2_misc == 0x4:
                inst.op = Op.DSB
                inst.imm = hw2 & 0xF
            elif op2_misc == 0x5:
                inst.op = Op.DMB
                inst.imm = hw2 & 0xF
            elif op2_misc == 0x6:
                inst.op = Op.ISB
                inst.imm = hw2 & 0xF
            else:
                inst.op = Op.NOP
        elif (op & 0x7B) == 0x39:
            # MRS
            rd = (hw2 >> 8) & 0xF
            sysm = hw2 & 0xFF
            inst.op = Op.MRS
            inst.rd = rd
            inst.imm = sysm
            self._decode_sysreg(inst, sysm, is_write=False)
        else:
            inst.op = Op.UNKNOWN

    def _decode_sysreg(self, inst, sysm, is_write):
        """Decode system register for MSR/MRS."""
        reg_map = {
            0: 'APSR',
            1: 'IAPSR',
            2: 'EAPSR',
            3: 'xPSR',
            5: 'IPSR',
            6: 'EPSR',
            7: 'IEPSR',
            8: 'MSP',
            9: 'PSP',
            16: 'PRIMASK',
            17: 'BASEPRI',
            18: 'BASEPRI_MAX',
            19: 'FAULTMASK',
            20: 'CONTROL',
        }
        inst.sysreg = reg_map.get(sysm, f'UNKNOWN_{sysm}')

    # ---------------------------------------------------------------
    # 32-bit: Store Single
    # ---------------------------------------------------------------

    def _decode_t32_store_single(self, hw1, hw2, inst):
        op1 = (hw1 >> 5) & 0x7
        op2 = (hw2 >> 6) & 0x3F
        rn = hw1 & 0xF
        rt = (hw2 >> 12) & 0xF

        inst.rt = rt
        inst.rn = rn

        size_map = {0: Op.STRB, 1: Op.STRH, 2: Op.STR}

        size = op1 & 0x3
        if op1 & 0x4:
            # Immediate 12-bit
            inst.op = size_map.get(size, Op.UNKNOWN)
            inst.imm = hw2 & 0xFFF
            inst.index = True
            inst.add = True
        else:
            if (op2 & 0x20) == 0x20:
                # Pre/post indexed with 8-bit imm
                inst.op = size_map.get(size, Op.UNKNOWN)
                p = bool(hw2 & (1 << 10))
                u = bool(hw2 & (1 << 9))
                w = bool(hw2 & (1 << 8))
                inst.imm = hw2 & 0xFF
                inst.index = p
                inst.add = u
                inst.wback = w
            elif (op2 & 0x3C) == 0x00:
                # Register offset
                inst.op = size_map.get(size, Op.UNKNOWN)
                inst.rm = hw2 & 0xF
                inst.shift_type = SHIFT_LSL
                inst.shift_n = (hw2 >> 4) & 0x3
                inst.index = True
                inst.add = True
            else:
                inst.op = Op.UNKNOWN

    # ---------------------------------------------------------------
    # 32-bit: Load Byte
    # ---------------------------------------------------------------

    def _decode_t32_load_byte(self, hw1, hw2, inst):
        op1 = (hw1 >> 7) & 0x3
        rn = hw1 & 0xF
        rt = (hw2 >> 12) & 0xF

        inst.rt = rt
        inst.rn = rn

        if op1 == 0:
            # LDRB
            if rn == 15:
                inst.op = Op.LDRB
                inst.imm = hw2 & 0xFFF
                inst.add = bool(hw1 & (1 << 7))
            elif (hw2 & 0x800) == 0x800:
                inst.op = Op.LDRB
                inst.imm = hw2 & 0xFFF
                inst.index = True
                inst.add = True
            elif (hw2 & 0xF00) == 0xC00:
                inst.op = Op.LDRB
                p = bool(hw2 & (1 << 10))
                u = bool(hw2 & (1 << 9))
                w = bool(hw2 & (1 << 8))
                inst.imm = hw2 & 0xFF
                inst.index = p
                inst.add = u
                inst.wback = w
            else:
                inst.op = Op.LDRB
                inst.rm = hw2 & 0xF
                inst.shift_type = SHIFT_LSL
                inst.shift_n = (hw2 >> 4) & 0x3
                inst.index = True
                inst.add = True
        elif op1 == 1:
            # LDRSB
            inst.op = Op.LDRSB
            if rn == 15:
                inst.imm = hw2 & 0xFFF
            elif (hw2 & 0x800) == 0x800:
                inst.imm = hw2 & 0xFFF
                inst.index = True
                inst.add = True
            elif (hw2 & 0xF00) == 0xC00:
                p = bool(hw2 & (1 << 10))
                u = bool(hw2 & (1 << 9))
                w = bool(hw2 & (1 << 8))
                inst.imm = hw2 & 0xFF
                inst.index = p
                inst.add = u
                inst.wback = w
            else:
                inst.rm = hw2 & 0xF
                inst.shift_type = SHIFT_LSL
                inst.shift_n = (hw2 >> 4) & 0x3
                inst.index = True
                inst.add = True
        else:
            inst.op = Op.UNKNOWN

    # ---------------------------------------------------------------
    # 32-bit: Load Halfword
    # ---------------------------------------------------------------

    def _decode_t32_load_halfword(self, hw1, hw2, inst):
        op1 = (hw1 >> 7) & 0x3
        rn = hw1 & 0xF
        rt = (hw2 >> 12) & 0xF

        inst.rt = rt
        inst.rn = rn

        if op1 == 0:
            inst.op = Op.LDRH
        elif op1 == 1:
            inst.op = Op.LDRSH
        else:
            inst.op = Op.UNKNOWN
            return

        if rn == 15:
            inst.imm = hw2 & 0xFFF
            inst.add = bool(hw1 & (1 << 7))
        elif (hw2 & 0x800) == 0x800:
            inst.imm = hw2 & 0xFFF
            inst.index = True
            inst.add = True
        elif (hw2 & 0xF00) == 0xC00:
            p = bool(hw2 & (1 << 10))
            u = bool(hw2 & (1 << 9))
            w = bool(hw2 & (1 << 8))
            inst.imm = hw2 & 0xFF
            inst.index = p
            inst.add = u
            inst.wback = w
        else:
            inst.rm = hw2 & 0xF
            inst.shift_type = SHIFT_LSL
            inst.shift_n = (hw2 >> 4) & 0x3
            inst.index = True
            inst.add = True

    # ---------------------------------------------------------------
    # 32-bit: Load Word
    # ---------------------------------------------------------------

    def _decode_t32_load_word(self, hw1, hw2, inst):
        rn = hw1 & 0xF
        rt = (hw2 >> 12) & 0xF

        inst.op = Op.LDR
        inst.rt = rt
        inst.rn = rn

        if rn == 15:
            # LDR (literal)
            inst.op = Op.LDR_LIT
            inst.imm = hw2 & 0xFFF
            inst.add = bool(hw1 & (1 << 7))
        elif (hw1 >> 7) & 1:
            # LDR.W Rt, [Rn, #imm12]
            inst.imm = hw2 & 0xFFF
            inst.index = True
            inst.add = True
        elif (hw2 & 0x800) == 0x800:
            # LDR Rt, [Rn, #imm8] with pre/post/writeback
            p = bool(hw2 & (1 << 10))
            u = bool(hw2 & (1 << 9))
            w = bool(hw2 & (1 << 8))
            inst.imm = hw2 & 0xFF
            inst.index = p
            inst.add = u
            inst.wback = w
        else:
            # LDR Rt, [Rn, Rm, LSL #imm2]
            inst.rm = hw2 & 0xF
            inst.shift_type = SHIFT_LSL
            inst.shift_n = (hw2 >> 4) & 0x3
            inst.index = True
            inst.add = True

    # ---------------------------------------------------------------
    # 32-bit: Data Processing (Register)
    # ---------------------------------------------------------------

    def _decode_t32_data_proc_reg(self, hw1, hw2, inst):
        op1 = (hw1 >> 4) & 0xF
        op2 = (hw2 >> 4) & 0xF
        rn = hw1 & 0xF
        rd = (hw2 >> 8) & 0xF
        rm = hw2 & 0xF

        inst.rd = rd
        inst.rn = rn
        inst.rm = rm

        if op1 == 0x0 and op2 == 0x0:
            # LSL (register)
            inst.op = Op.LSL
            inst.rs = rm
            inst.rm = None
        elif op1 == 0x1 and op2 == 0x0:
            # LSR (register)
            inst.op = Op.LSR
            inst.rs = rm
            inst.rm = None
        elif op1 == 0x2 and op2 == 0x0:
            # ASR (register)
            inst.op = Op.ASR
            inst.rs = rm
            inst.rm = None
        elif op1 == 0x3 and op2 == 0x0:
            # ROR (register)
            inst.op = Op.ROR
            inst.rs = rm
            inst.rm = None
        elif op1 in (0x0, 0x1, 0x2, 0x3) and (op2 & 0x8):
            # Extend with optional add
            rotation = ((hw2 >> 4) & 0x3) * 8
            inst.rotation = rotation
            if op1 == 0x0:
                inst.op = Op.SXTAH if rn != 15 else Op.SXTH
            elif op1 == 0x1:
                inst.op = Op.UXTAH if rn != 15 else Op.UXTH
            elif op1 == 0x2:
                inst.op = Op.SXTAB if rn != 15 else Op.SXTB
            elif op1 == 0x3:
                inst.op = Op.UXTAB if rn != 15 else Op.UXTB
            if rn == 15:
                inst.rn = None
        elif op1 == 0x4 and op2 == 0x0:
            # Misc: might be several things
            # Check for RBIT, REV, REV16, REVSH, CLZ
            pass
        elif (op1 & 0xC) == 0x8:
            # Misc operations
            sub = op2 & 0x3
            if op1 == 0x8 and sub == 0x0:
                inst.op = Op.REV
            elif op1 == 0x8 and sub == 0x1:
                inst.op = Op.REV16
            elif op1 == 0x8 and sub == 0x2:
                inst.op = Op.RBIT
            elif op1 == 0x8 and sub == 0x3:
                inst.op = Op.REVSH
            elif op1 == 0xB and sub == 0x0:
                inst.op = Op.CLZ
        else:
            inst.op = Op.UNKNOWN

    # ---------------------------------------------------------------
    # 32-bit: Multiply (32-bit result)
    # ---------------------------------------------------------------

    def _decode_t32_multiply(self, hw1, hw2, inst):
        op1 = (hw1 >> 4) & 0x7
        op2 = (hw2 >> 4) & 0x3
        rn = hw1 & 0xF
        rd = (hw2 >> 8) & 0xF
        rm = hw2 & 0xF
        ra = (hw2 >> 12) & 0xF

        inst.rd = rd
        inst.rn = rn
        inst.rm = rm

        if op1 == 0x0:
            if ra == 15:
                inst.op = Op.MUL
            elif op2 == 0x0:
                inst.op = Op.MLA
                inst.rs = ra  # accumulate register
            elif op2 == 0x1:
                inst.op = Op.MLS
                inst.rs = ra
        elif op1 == 0x1:
            if op2 == 0x0:
                inst.op = Op.SDIV
            else:
                inst.op = Op.UNKNOWN
        elif op1 == 0x3:
            if op2 == 0x0:
                inst.op = Op.UDIV
            else:
                inst.op = Op.UNKNOWN
        else:
            inst.op = Op.UNKNOWN

    # ---------------------------------------------------------------
    # 32-bit: Long Multiply / Divide (64-bit result)
    # ---------------------------------------------------------------

    def _decode_t32_long_multiply(self, hw1, hw2, inst):
        op1 = (hw1 >> 4) & 0x7
        op2 = (hw2 >> 4) & 0xF
        rn = hw1 & 0xF
        rdlo = (hw2 >> 12) & 0xF
        rdhi = (hw2 >> 8) & 0xF
        rm = hw2 & 0xF

        inst.rn = rn
        inst.rm = rm
        inst.rdlo = rdlo
        inst.rdhi = rdhi

        if op1 == 0x0:
            if op2 == 0x0:
                inst.op = Op.SMULL
            else:
                inst.op = Op.UNKNOWN
        elif op1 == 0x2:
            if op2 == 0x0:
                inst.op = Op.UMULL
            else:
                inst.op = Op.UNKNOWN
        elif op1 == 0x4:
            inst.op = Op.SMLAL
        elif op1 == 0x6:
            inst.op = Op.UMLAL
        else:
            inst.op = Op.UNKNOWN

    # ---------------------------------------------------------------
    # 32-bit: Coprocessor (stub)
    # ---------------------------------------------------------------

    def _decode_t32_coprocessor(self, hw1, hw2, inst):
        inst.op = Op.UNKNOWN

    # ---------------------------------------------------------------
    # 32-bit: Undefined
    # ---------------------------------------------------------------

    def _decode_t32_undefined(self, hw1, hw2, inst):
        inst.op = Op.UNDEFINED
"""
ARM Cortex-M7 ALU (Arithmetic Logic Unit)

Все операции работают с 32-битными беззнаковыми значениями.
Флаги возвращаются отдельно, PSR обновляется вызывающим кодом.
"""


def to_signed32(value):
    """Преобразовать 32-битное беззнаковое в знаковое."""
    value &= 0xFFFFFFFF
    if value & 0x80000000:
        return value - 0x100000000
    return value


def to_unsigned32(value):
    """Преобразовать знаковое в 32-битное беззнаковое."""
    return value & 0xFFFFFFFF


def sign_extend(value, bits):
    """Знаковое расширение из bits до 32 бит."""
    sign_bit = 1 << (bits - 1)
    mask = (1 << bits) - 1
    value &= mask
    if value & sign_bit:
        value |= 0xFFFFFFFF << bits
    return value & 0xFFFFFFFF


# ===========================================================
# Арифметические операции
# ===========================================================

def add_with_carry(a, b, carry_in):
    """
    AddWithCarry (основа для ADD, ADC, SUB, SBC, CMP, CMN).
    
    Возвращает (result, carry_out, overflow).
    """
    a &= 0xFFFFFFFF
    b &= 0xFFFFFFFF
    carry_in = 1 if carry_in else 0

    # Полное сложение
    unsigned_sum = a + b + carry_in
    result = unsigned_sum & 0xFFFFFFFF

    # Carry: результат не помещается в 32 бита
    carry_out = unsigned_sum > 0xFFFFFFFF

    # Overflow: знак результата неправильный
    # Происходит когда оба операнда одного знака, а результат — другого
    a_sign = a & 0x80000000
    b_sign = b & 0x80000000
    r_sign = result & 0x80000000
    overflow = bool((a_sign == b_sign) and (a_sign != r_sign))

    return result, carry_out, overflow


def alu_add(a, b):
    """ADD: a + b → (result, carry, overflow)"""
    return add_with_carry(a, b, 0)


def alu_adc(a, b, carry_in):
    """ADC: a + b + C → (result, carry, overflow)"""
    return add_with_carry(a, b, carry_in)


def alu_sub(a, b):
    """SUB: a - b → (result, carry, overflow)
    
    SUB = AddWithCarry(a, NOT(b), 1)
    Carry = NOT(borrow): carry=1 означает НЕТ заёма.
    """
    return add_with_carry(a, (~b) & 0xFFFFFFFF, 1)


def alu_sbc(a, b, carry_in):
    """SBC: a - b - !C → (result, carry, overflow)
    
    SBC = AddWithCarry(a, NOT(b), C)
    """
    return add_with_carry(a, (~b) & 0xFFFFFFFF, carry_in)


def alu_rsb(a, b):
    """RSB (Reverse Subtract): b - a → (result, carry, overflow)"""
    return add_with_carry((~a) & 0xFFFFFFFF, b, 1)


# ===========================================================
# Логические операции
# ===========================================================

def alu_and(a, b):
    """AND: a & b"""
    return (a & b) & 0xFFFFFFFF


def alu_orr(a, b):
    """ORR: a | b"""
    return (a | b) & 0xFFFFFFFF


def alu_eor(a, b):
    """EOR (XOR): a ^ b"""
    return (a ^ b) & 0xFFFFFFFF


def alu_orn(a, b):
    """ORN: a | ~b"""
    return (a | (~b)) & 0xFFFFFFFF


def alu_bic(a, b):
    """BIC (Bit Clear): a & ~b"""
    return (a & (~b)) & 0xFFFFFFFF


def alu_mvn(b):
    """MVN (Move Not): ~b"""
    return (~b) & 0xFFFFFFFF


# ===========================================================
# Сдвиги
# ===========================================================

def shift_lsl(value, amount, carry_in):
    """
    Logical Shift Left.
    Возвращает (result, carry_out).
    """
    value &= 0xFFFFFFFF
    if amount == 0:
        return value, carry_in
    if amount < 32:
        carry_out = bool(value & (1 << (32 - amount)))
        result = (value << amount) & 0xFFFFFFFF
        return result, carry_out
    if amount == 32:
        carry_out = bool(value & 1)
        return 0, carry_out
    # amount > 32
    return 0, False


def shift_lsr(value, amount, carry_in):
    """
    Logical Shift Right.
    Возвращает (result, carry_out).
    """
    value &= 0xFFFFFFFF
    if amount == 0:
        return value, carry_in
    if amount < 32:
        carry_out = bool(value & (1 << (amount - 1)))
        result = value >> amount
        return result, carry_out
    if amount == 32:
        carry_out = bool(value & 0x80000000)
        return 0, carry_out
    # amount > 32
    return 0, False


def shift_asr(value, amount, carry_in):
    """
    Arithmetic Shift Right (знаковый сдвиг вправо).
    Возвращает (result, carry_out).
    """
    value &= 0xFFFFFFFF
    if amount == 0:
        return value, carry_in
    signed = to_signed32(value)
    if amount < 32:
        carry_out = bool(value & (1 << (amount - 1)))
        result = to_unsigned32(signed >> amount)
        return result, carry_out
    # amount >= 32: результат = 0 или 0xFFFFFFFF в зависимости от знака
    if signed < 0:
        return 0xFFFFFFFF, True
    return 0, False


def shift_ror(value, amount, carry_in):
    """
    Rotate Right.
    Возвращает (result, carry_out).
    """
    value &= 0xFFFFFFFF
    if amount == 0:
        return value, carry_in
    amount = amount % 32
    if amount == 0:
        # Rotate на 32 — результат тот же, carry = MSB
        carry_out = bool(value & 0x80000000)
        return value, carry_out
    result = ((value >> amount) | (value << (32 - amount))) & 0xFFFFFFFF
    carry_out = bool(result & 0x80000000)
    return result, carry_out


def shift_rrx(value, carry_in):
    """
    Rotate Right with Extend (сдвиг на 1 через carry).
    Возвращает (result, carry_out).
    """
    value &= 0xFFFFFFFF
    carry_out = bool(value & 1)
    result = (value >> 1) | (0x80000000 if carry_in else 0)
    return result, carry_out


# Типы сдвигов (кодировка в инструкциях)
SHIFT_LSL = 0
SHIFT_LSR = 1
SHIFT_ASR = 2
SHIFT_ROR = 3

def apply_shift(value, shift_type, amount, carry_in):
    """
    Применить сдвиг по типу (0=LSL, 1=LSR, 2=ASR, 3=ROR/RRX).
    
    Для type=3, amount=0 → RRX, иначе ROR.
    Возвращает (result, carry_out).
    """
    if shift_type == SHIFT_LSL:
        return shift_lsl(value, amount, carry_in)
    elif shift_type == SHIFT_LSR:
        if amount == 0:
            amount = 32  # LSR #0 кодирует LSR #32
        return shift_lsr(value, amount, carry_in)
    elif shift_type == SHIFT_ASR:
        if amount == 0:
            amount = 32  # ASR #0 кодирует ASR #32
        return shift_asr(value, amount, carry_in)
    elif shift_type == SHIFT_ROR:
        if amount == 0:
            return shift_rrx(value, carry_in)
        return shift_ror(value, amount, carry_in)
    else:
        raise ValueError(f"Unknown shift type: {shift_type}")


# ===========================================================
# Thumb-2 Immediate: расширение modified immediate constant
# ===========================================================

def thumb_expand_imm(imm12, carry_in):
    """
    Расширение 12-битного Thumb-2 modified immediate.
    
    Биты [11:8] определяют тип преобразования,
    биты [7:0] — значение.
    
    Возвращает (result, carry_out).
    """
    top4 = (imm12 >> 8) & 0xF
    bottom8 = imm12 & 0xFF

    if top4 == 0:
        # 00000000 00000000 00000000 abcdefgh
        return bottom8, carry_in
    elif top4 == 1:
        # 00000000 abcdefgh 00000000 abcdefgh
        return (bottom8 | (bottom8 << 16)), carry_in
    elif top4 == 2:
        # abcdefgh 00000000 abcdefgh 00000000
        return ((bottom8 << 8) | (bottom8 << 24)), carry_in
    elif top4 == 3:
        # abcdefgh abcdefgh abcdefgh abcdefgh
        val = bottom8 | (bottom8 << 8) | (bottom8 << 16) | (bottom8 << 24)
        return val, carry_in
    else:
        # ROR вращение: 1bcdefgh вращается вправо
        unrotated = 0x80 | bottom8  # восстановить ведущую 1
        rotation = top4 << 1
        # Используем бит a (бит 7 из imm12) как доп. бит вращения
        # Полное вращение = (top4 << 1) | a, где a — бит 7 imm12
        # Но top4 уже содержит биты [11:8], нужно 5-битное вращение
        # rotation = bits[11:7] = (imm12 >> 7) & 0x1F
        rotation = (imm12 >> 7) & 0x1F
        result, carry_out = shift_ror(unrotated, rotation, carry_in)
        return result, carry_out


def thumb_expand_imm_c(imm12, carry_in):
    """То же что thumb_expand_imm, возвращает (value, carry)."""
    return thumb_expand_imm(imm12, carry_in)


# ===========================================================
# Умножение и деление
# ===========================================================

def alu_mul(a, b):
    """MUL: (a * b) нижние 32 бита."""
    return (a * b) & 0xFFFFFFFF


def alu_smull(a, b):
    """SMULL: знаковое 32x32→64. Возвращает (lo, hi)."""
    sa = to_signed32(a)
    sb = to_signed32(b)
    result = sa * sb
    lo = result & 0xFFFFFFFF
    hi = (result >> 32) & 0xFFFFFFFF
    return lo, hi


def alu_umull(a, b):
    """UMULL: беззнаковое 32x32→64. Возвращает (lo, hi)."""
    a &= 0xFFFFFFFF
    b &= 0xFFFFFFFF
    result = a * b
    lo = result & 0xFFFFFFFF
    hi = (result >> 32) & 0xFFFFFFFF
    return lo, hi


def alu_mla(a, b, acc):
    """MLA: (a * b + acc) нижние 32 бита."""
    return ((a * b) + acc) & 0xFFFFFFFF


def alu_mls(a, b, acc):
    """MLS: (acc - a * b) нижние 32 бита."""
    return (acc - (a * b)) & 0xFFFFFFFF


def alu_sdiv(a, b):
    """SDIV: знаковое деление. Деление на 0 → 0."""
    if b == 0:
        return 0
    sa = to_signed32(a)
    sb = to_signed32(b)
    # ARM округляет к нулю
    if (sa < 0) != (sb < 0):
        result = -(abs(sa) // abs(sb))
    else:
        result = abs(sa) // abs(sb)
    return to_unsigned32(result)


def alu_udiv(a, b):
    """UDIV: беззнаковое деление. Деление на 0 → 0."""
    a &= 0xFFFFFFFF
    b &= 0xFFFFFFFF
    if b == 0:
        return 0
    return a // b


# ===========================================================
# Битовые операции
# ===========================================================

def count_leading_zeros(value):
    """CLZ: количество ведущих нулей."""
    value &= 0xFFFFFFFF
    if value == 0:
        return 32
    count = 0
    for i in range(31, -1, -1):
        if value & (1 << i):
            break
        count += 1
    return count


def bit_field_extract_unsigned(value, lsb, width):
    """UBFX: извлечь битовое поле беззнаково."""
    value &= 0xFFFFFFFF
    mask = (1 << width) - 1
    return (value >> lsb) & mask


def bit_field_extract_signed(value, lsb, width):
    """SBFX: извлечь битовое поле со знаковым расширением."""
    extracted = bit_field_extract_unsigned(value, lsb, width)
    return sign_extend(extracted, width)


def bit_field_insert(dest, source, lsb, width):
    """BFI: вставить битовое поле."""
    dest &= 0xFFFFFFFF
    source &= 0xFFFFFFFF
    mask = ((1 << width) - 1) << lsb
    bits = ((source & ((1 << width) - 1)) << lsb)
    return (dest & ~mask) | bits


def bit_field_clear(dest, lsb, width):
    """BFC: очистить битовое поле."""
    dest &= 0xFFFFFFFF
    mask = ((1 << width) - 1) << lsb
    return dest & ~mask


def reverse_bits(value):
    """RBIT: перевернуть все 32 бита."""
    value &= 0xFFFFFFFF
    result = 0
    for i in range(32):
        if value & (1 << i):
            result |= 1 << (31 - i)
    return result


def reverse_bytes(value):
    """REV: перевернуть порядок байтов (byte swap)."""
    value &= 0xFFFFFFFF
    b0 = value & 0xFF
    b1 = (value >> 8) & 0xFF
    b2 = (value >> 16) & 0xFF
    b3 = (value >> 24) & 0xFF
    return (b0 << 24) | (b1 << 16) | (b2 << 8) | b3


def reverse_bytes_16(value):
    """REV16: перевернуть байты в каждом полуслове."""
    value &= 0xFFFFFFFF
    lo = ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)
    hi = (((value >> 16) & 0xFF) << 8) | ((value >> 24) & 0xFF)
    return (hi << 16) | lo


def reverse_bytes_signed_16(value):
    """REVSH: перевернуть байты нижнего полуслова, знаково расширить."""
    value &= 0xFFFF
    swapped = ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)
    return sign_extend(swapped, 16)


# ===========================================================
# Насыщение (Saturation)
# ===========================================================

def signed_saturate(value, sat_to):
    """
    Signed saturation к sat_to битам.
    Возвращает (result, saturated).
    """
    max_val = (1 << (sat_to - 1)) - 1
    min_val = -(1 << (sat_to - 1))
    signed_val = to_signed32(value)
    if signed_val > max_val:
        return to_unsigned32(max_val), True
    if signed_val < min_val:
        return to_unsigned32(min_val), True
    return to_unsigned32(signed_val), False


def unsigned_saturate(value, sat_to):
    """
    Unsigned saturation к sat_to битам.
    Возвращает (result, saturated).
    """
    max_val = (1 << sat_to) - 1
    signed_val = to_signed32(value)
    if signed_val > max_val:
        return max_val, True
    if signed_val < 0:
        return 0, True
    return value & 0xFFFFFFFF, False


# ===========================================================
# Расширения (extend)
# ===========================================================

def extend_byte_signed(value, rotation=0):
    """SXTB: знаковое расширение байта."""
    value = (value >> rotation) & 0xFF
    return sign_extend(value, 8)


def extend_halfword_signed(value, rotation=0):
    """SXTH: знаковое расширение полуслова."""
    value = (value >> rotation) & 0xFFFF
    return sign_extend(value, 16)


def extend_byte_unsigned(value, rotation=0):
    """UXTB: беззнаковое расширение байта."""
    return (value >> rotation) & 0xFF


def extend_halfword_unsigned(value, rotation=0):
    """UXTH: беззнаковое расширение полуслова."""
    return (value >> rotation) & 0xFFFF
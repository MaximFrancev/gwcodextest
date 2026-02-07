import unittest

from gwemu.cpu import CortexMEmulator, FLASH_BASE, SRAM_BASE, build_default_memory


class CortexMEmulatorTests(unittest.TestCase):
    def _run(self, program: bytes) -> CortexMEmulator:
        memory = build_default_memory(program)
        cpu = CortexMEmulator(memory)
        cpu.reset()
        while not cpu.halted:
            cpu.step()
        return cpu

    def test_mov_add_sub(self) -> None:
        program = bytearray()
        program += (0x20002000).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        program += (0x2001).to_bytes(2, "little")  # MOVS r0, #1
        program += (0x3002).to_bytes(2, "little")  # ADDS r0, #2
        program += (0x3801).to_bytes(2, "little")  # SUBS r0, #1
        program += (0xBE00).to_bytes(2, "little")

        cpu = self._run(program)
        self.assertEqual(cpu.regs[0], 2)

    def test_branch(self) -> None:
        program = bytearray()
        program += (0x20001000).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        program += (0xE001).to_bytes(2, "little")  # B +4
        program += (0x2105).to_bytes(2, "little")  # MOVS r1, #5
        program += (0x2107).to_bytes(2, "little")  # MOVS r1, #7
        program += (0xBE00).to_bytes(2, "little")

        cpu = self._run(program)
        self.assertEqual(cpu.regs[1], 7)

    def test_ldr_literal(self) -> None:
        program = bytearray()
        program += (0x20001000).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        program += (0x4A00).to_bytes(2, "little")  # LDR r2, [PC, #0]
        program += (0xBE00).to_bytes(2, "little")
        program += (0xDEADBEEF).to_bytes(4, "little")

        cpu = self._run(program)
        self.assertEqual(cpu.regs[2], 0xDEADBEEF)

    def test_str_ldr_immediate(self) -> None:
        program = bytearray()
        program += (SRAM_BASE + 0x100).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        program += (0x4802).to_bytes(2, "little")  # LDR r0, [PC, #8]
        program += (0x2102).to_bytes(2, "little")  # MOVS r1, #2
        program += (0x6001).to_bytes(2, "little")  # STR r1, [r0, #0]
        program += (0x6802).to_bytes(2, "little")  # LDR r2, [r0, #0]
        program += (0xBE00).to_bytes(2, "little")
        program += (0xBF00).to_bytes(2, "little")
        program += (SRAM_BASE + 0x80).to_bytes(4, "little")

        cpu = self._run(program)
        self.assertEqual(cpu.regs[2], 2)

    def test_push_pop(self) -> None:
        program = bytearray()
        program += (SRAM_BASE + 0x200).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        program += (0x2001).to_bytes(2, "little")  # MOVS r0, #1
        program += (0x2102).to_bytes(2, "little")  # MOVS r1, #2
        program += (0xB403).to_bytes(2, "little")  # PUSH {r0, r1}
        program += (0x2000).to_bytes(2, "little")  # MOVS r0, #0
        program += (0x2100).to_bytes(2, "little")  # MOVS r1, #0
        program += (0xBC03).to_bytes(2, "little")  # POP {r0, r1}
        program += (0xBE00).to_bytes(2, "little")

        cpu = self._run(program)
        self.assertEqual(cpu.regs[0], 1)
        self.assertEqual(cpu.regs[1], 2)

    def test_shift_immediate(self) -> None:
        program = bytearray()
        program += (0x20001000).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        program += (0x2008).to_bytes(2, "little")  # MOVS r0, #8
        program += (0x00C1).to_bytes(2, "little")  # LSLS r1, r0, #3
        program += (0x0842).to_bytes(2, "little")  # LSRS r2, r0, #1
        program += (0x10C3).to_bytes(2, "little")  # ASRS r3, r0, #3
        program += (0xBE00).to_bytes(2, "little")

        cpu = self._run(program)
        self.assertEqual(cpu.regs[1], 64)
        self.assertEqual(cpu.regs[2], 4)
        self.assertEqual(cpu.regs[3], 1)

    def test_cmp_immediate(self) -> None:
        program = bytearray()
        program += (0x20001000).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        program += (0x2005).to_bytes(2, "little")  # MOVS r0, #5
        program += (0x2803).to_bytes(2, "little")  # CMP r0, #3
        program += (0xD101).to_bytes(2, "little")  # BNE skip
        program += (0x2001).to_bytes(2, "little")  # MOVS r0, #1 (should skip)
        program += (0xBE00).to_bytes(2, "little")

        cpu = self._run(program)
        self.assertEqual(cpu.regs[0], 5)

    def test_mov_high_register(self) -> None:
        program = bytearray()
        program += (0x20001000).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        program += (0x2007).to_bytes(2, "little")  # MOVS r0, #7
        program += (0x4680).to_bytes(2, "little")  # MOV r8, r0
        program += (0xBE00).to_bytes(2, "little")

        cpu = self._run(program)
        self.assertEqual(cpu.regs[8], 7)

    def test_ldm_stm(self) -> None:
        program = bytearray()
        program += (SRAM_BASE + 0x100).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        program += (0x4803).to_bytes(2, "little")  # LDR r0, [PC, #12]
        program += (0x2102).to_bytes(2, "little")  # MOVS r1, #2
        program += (0xC002).to_bytes(2, "little")  # STMIA r0!, {r1}
        program += (0x4802).to_bytes(2, "little")  # LDR r0, [PC, #8]
        program += (0xC804).to_bytes(2, "little")  # LDMIA r0!, {r2}
        program += (0xBE00).to_bytes(2, "little")
        program += (0xBF00).to_bytes(2, "little")
        program += (0xBF00).to_bytes(2, "little")
        program += (SRAM_BASE + 0x80).to_bytes(4, "little")

        cpu = self._run(program)
        self.assertEqual(cpu.regs[2], 2)


if __name__ == "__main__":
    unittest.main()

import unittest

from gwemu.cpu import CortexMEmulator, build_default_memory, FLASH_BASE


class CortexMEmulatorTests(unittest.TestCase):
    def test_mov_add_sub(self) -> None:
        # Vector table: initial SP, reset handler.
        program = bytearray()
        program += (0x20002000).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        # Instructions: MOVS r0, #1; ADDS r0, #2; SUBS r0, #1; BKPT
        program += (0x2001).to_bytes(2, "little")
        program += (0x3002).to_bytes(2, "little")
        program += (0x3801).to_bytes(2, "little")
        program += (0xBE00).to_bytes(2, "little")

        memory = build_default_memory(program)
        cpu = CortexMEmulator(memory)
        cpu.reset()

        while not cpu.halted:
            cpu.step()

        self.assertEqual(cpu.regs[0], 2)

    def test_branch(self) -> None:
        program = bytearray()
        program += (0x20001000).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        # 0: B +4 (skip next instruction)
        program += (0xE001).to_bytes(2, "little")
        # 2: MOVS r1, #5 (should be skipped)
        program += (0x2105).to_bytes(2, "little")
        # 4: MOVS r1, #7
        program += (0x2107).to_bytes(2, "little")
        # 6: BKPT
        program += (0xBE00).to_bytes(2, "little")

        memory = build_default_memory(program)
        cpu = CortexMEmulator(memory)
        cpu.reset()

        while not cpu.halted:
            cpu.step()

        self.assertEqual(cpu.regs[1], 7)

    def test_ldr_literal(self) -> None:
        program = bytearray()
        program += (0x20001000).to_bytes(4, "little")
        program += (FLASH_BASE + 8).to_bytes(4, "little")
        # LDR r2, [PC, #0]
        program += (0x4A00).to_bytes(2, "little")
        # BKPT
        program += (0xBE00).to_bytes(2, "little")
        # literal word (aligned)
        program += (0xDEADBEEF).to_bytes(4, "little")

        memory = build_default_memory(program)
        cpu = CortexMEmulator(memory)
        cpu.reset()

        while not cpu.halted:
            cpu.step()

        self.assertEqual(cpu.regs[2], 0xDEADBEEF)


if __name__ == "__main__":
    unittest.main()

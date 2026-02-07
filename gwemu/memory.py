from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class MemoryRegion:
    base: int
    size: int
    data: bytearray
    read_only: bool = False

    def contains(self, address: int, length: int = 1) -> bool:
        return self.base <= address and (address + length) <= (self.base + self.size)

    def read(self, address: int, length: int) -> bytes:
        offset = address - self.base
        return bytes(self.data[offset : offset + length])

    def write(self, address: int, payload: bytes) -> None:
        if self.read_only:
            return
        offset = address - self.base
        self.data[offset : offset + len(payload)] = payload


class MemoryMap:
    def __init__(self) -> None:
        self._regions: List[MemoryRegion] = []

    def add_region(self, region: MemoryRegion) -> None:
        self._regions.append(region)

    def _find_region(self, address: int, length: int = 1) -> MemoryRegion:
        for region in self._regions:
            if region.contains(address, length):
                return region
        raise ValueError(f"Unmapped memory access at 0x{address:08X}")

    def read8(self, address: int) -> int:
        return self._find_region(address).read(address, 1)[0]

    def read16(self, address: int) -> int:
        data = self._find_region(address, 2).read(address, 2)
        return int.from_bytes(data, "little")

    def read32(self, address: int) -> int:
        data = self._find_region(address, 4).read(address, 4)
        return int.from_bytes(data, "little")

    def write8(self, address: int, value: int) -> None:
        self._find_region(address).write(address, bytes([value & 0xFF]))

    def write16(self, address: int, value: int) -> None:
        self._find_region(address).write(address, value.to_bytes(2, "little"))

    def write32(self, address: int, value: int) -> None:
        self._find_region(address).write(address, value.to_bytes(4, "little"))

    def load(self, address: int, payload: bytes) -> None:
        self._find_region(address, len(payload)).write(address, payload)

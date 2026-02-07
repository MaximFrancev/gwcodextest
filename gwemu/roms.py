from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RomSet:
    internal_flash: bytes
    external_flash: bytes | None = None
    itcm: bytes | None = None


def load_rom_file(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read()


def load_rom_set(path: Path) -> RomSet:
    if path.is_file():
        return RomSet(internal_flash=load_rom_file(path))

    internal = path / "internal_flash.bin"
    external = path / "external_flash.bin"
    itcm = path / "itcm.bin"

    if not internal.exists():
        raise FileNotFoundError(
            "Expected internal_flash.bin inside the ROM directory."
        )

    return RomSet(
        internal_flash=load_rom_file(internal),
        external_flash=load_rom_file(external) if external.exists() else None,
        itcm=load_rom_file(itcm) if itcm.exists() else None,
    )


def find_rom_root(path: Path) -> Path:
    if path.is_file():
        return path

    candidates = list(path.glob("**/internal_flash.bin"))
    if not candidates:
        raise FileNotFoundError(
            f"No internal_flash.bin found under {path}. Provide a ROM path."
        )
    return candidates[0].parent

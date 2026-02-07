"""
External Flash Emulation (Macronix MX25U8035F)

Эмулирует 1MB внешнюю SPI Flash, подключённую через OCTOSPI.
Memory-mapped по адресу 0x90000000.

Game & Watch использует OTF (On-The-Fly) дешифрование:
- Регион 0x90000000-0x900FDFFF шифруется AES-CTR (OTF decryption)
- Регион 0x900FE000-0x900FEFFF шифруется AES-GCM
- Остальное — открытый текст

Мы поддерживаем загрузку как зашифрованного, так и расшифрованного дампа.
"""

import struct
import os
import json


class OTFDecryptor:
    """
    On-The-Fly AES дешифрование для external flash.
    
    Используется для дешифрования данных при чтении из memory-mapped региона.
    Если загружен уже расшифрованный дамп — дешифрование пропускается.
    """

    def __init__(self):
        self.enabled = False
        self.key = None          # 128-bit AES key (4 x uint32)
        self.nonce = None        # 64-bit nonce (2 x uint32)
        self.version = 0         # 16-bit version
        self.region = 0          # Region number
        self.start_addr = 0      # Start of encrypted region
        self.end_addr = 0        # End of encrypted region

    def configure(self, key, nonce, version, region, start, end):
        """Настроить параметры OTF дешифрования."""
        self.key = key
        self.nonce = nonce
        self.version = version
        self.region = region
        self.start_addr = start
        self.end_addr = end
        self.enabled = True

    def is_in_region(self, address):
        """Проверить, попадает ли адрес в зашифрованный регион."""
        if not self.enabled:
            return False
        return self.start_addr <= address <= self.end_addr

    def decrypt_block(self, address, data):
        """
        Расшифровать блок данных.
        
        В полной реализации здесь должен быть AES-CTR.
        Сейчас — заглушка (предполагаем расшифрованный дамп).
        """
        # TODO: Реализовать AES-CTR дешифрование если нужно
        # Для работы с расшифрованным дампом это не требуется
        return data


class AESGCMDecryptor:
    """
    AES-GCM дешифрование для защищённого региона external flash.
    """

    def __init__(self):
        self.enabled = False
        self.key = None
        self.iv = None
        self.base_addr = 0
        self.region_length = 0
        self.data_length = 0

    def configure(self, key, iv, base, region_length, data_length):
        """Настроить параметры AES-GCM."""
        self.key = key
        self.iv = iv
        self.base_addr = base
        self.region_length = region_length
        self.data_length = data_length
        self.enabled = True

    def is_in_region(self, address):
        if not self.enabled:
            return False
        return self.base_addr <= address < self.base_addr + self.region_length

    def decrypt_block(self, address, data):
        """Заглушка — предполагаем расшифрованный дамп."""
        return data


class ExternalFlash:
    """
    Внешняя SPI Flash (1MB), memory-mapped по адресу 0x90000000.
    
    Поддерживает:
    - Загрузку зашифрованного дампа (external_flash.bin)
    - Загрузку расшифрованного дампа (external_flash_decrypted.bin)
    - Загрузку ключей из (Key Info).json
    - OTF дешифрование при чтении (если загружен зашифрованный дамп)
    """

    BASE_ADDRESS = 0x90000000
    SIZE = 1024 * 1024  # 1MB
    END_ADDRESS = BASE_ADDRESS + SIZE - 1

    def __init__(self):
        self._data = bytearray([0xFF] * self.SIZE)
        self._decrypted = False  # True если загружен расшифрованный дамп

        self.otf_dec = OTFDecryptor()
        self.aes_gcm = AESGCMDecryptor()

    def contains(self, address):
        return self.BASE_ADDRESS <= address <= self.END_ADDRESS

    def _offset(self, address):
        off = address - self.BASE_ADDRESS
        if off < 0 or off >= self.SIZE:
            raise MemoryError(
                f"[EXT_FLASH] Address 0x{address:08X} out of range"
            )
        return off

    # === Чтение ===

    def read8(self, address):
        off = self._offset(address)
        val = self._data[off]

        if not self._decrypted:
            if self.otf_dec.is_in_region(address):
                decrypted = self.otf_dec.decrypt_block(address, bytes([val]))
                return decrypted[0]
            elif self.aes_gcm.is_in_region(address):
                decrypted = self.aes_gcm.decrypt_block(address, bytes([val]))
                return decrypted[0]

        return val

    def read16(self, address):
        off = self._offset(address)
        val = struct.unpack_from('<H', self._data, off)[0]

        if not self._decrypted:
            if self.otf_dec.is_in_region(address):
                raw = self._data[off:off + 2]
                decrypted = self.otf_dec.decrypt_block(address, bytes(raw))
                return struct.unpack('<H', decrypted)[0]
            elif self.aes_gcm.is_in_region(address):
                raw = self._data[off:off + 2]
                decrypted = self.aes_gcm.decrypt_block(address, bytes(raw))
                return struct.unpack('<H', decrypted)[0]

        return val

    def read32(self, address):
        off = self._offset(address)
        val = struct.unpack_from('<I', self._data, off)[0]

        if not self._decrypted:
            if self.otf_dec.is_in_region(address):
                raw = self._data[off:off + 4]
                decrypted = self.otf_dec.decrypt_block(address, bytes(raw))
                return struct.unpack('<I', decrypted)[0]
            elif self.aes_gcm.is_in_region(address):
                raw = self._data[off:off + 4]
                decrypted = self.aes_gcm.decrypt_block(address, bytes(raw))
                return struct.unpack('<I', decrypted)[0]

        return val

    def read_block(self, address, size):
        off = self._offset(address)
        end = min(off + size, self.SIZE)
        return bytes(self._data[off:end])

    # === Запись (Flash — read only) ===

    def write8(self, address, value):
        pass

    def write16(self, address, value):
        pass

    def write32(self, address, value):
        pass

    # === Загрузка ===

    def load_from_file(self, filepath):
        """
        Загрузить дамп external flash из файла.
        
        Автоматически определяет тип (зашифрованный / расшифрованный)
        по имени файла.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"External flash image not found: {filepath}")

        with open(filepath, 'rb') as f:
            data = f.read()

        size = min(len(data), self.SIZE)
        self._data[:size] = data[:size]

        # Определяем тип по имени файла
        basename = os.path.basename(filepath).lower()
        if 'decrypted' in basename:
            self._decrypted = True
        else:
            self._decrypted = False

        return size

    def load_decrypted(self, filepath):
        """Загрузить расшифрованный дамп."""
        size = self.load_from_file(filepath)
        self._decrypted = True
        return size

    def load_encrypted(self, filepath):
        """Загрузить зашифрованный дамп."""
        size = self.load_from_file(filepath)
        self._decrypted = False
        return size

    def load_keys(self, key_info_path):
        """
        Загрузить ключи шифрования из (Key Info).json.
        
        Формат файла:
        {
            "OtfDecKey": ["0x...", "0x...", "0x...", "0x..."],
            "OtfDecNonce": ["0x...", "0x..."],
            "OtfDecVersion": "0x...",
            "OtfDecRegion": 3,
            "OtfDecStart": "0x90000000",
            "OtfDecEnd": "0x900FDFFF",
            "AesGcmKey": ["0x...", "0x...", "0x...", "0x..."],
            "AesGcmIv": ["0x...", "0x...", "0x..."],
            "AesGcmBase": "0x900FE000",
            "AesGcmRegionLength": "0x1000",
            "AesGcmDataLength": "0x40"
        }
        """
        if not os.path.exists(key_info_path):
            print(f"[EXT_FLASH] Key info not found: {key_info_path}")
            return False

        with open(key_info_path, 'r') as f:
            info = json.load(f)

        try:
            # Parse OTF decryption parameters
            otf_key = [self._parse_hex(x) for x in info.get('OtfDecKey', [])]
            otf_nonce = [self._parse_hex(x) for x in info.get('OtfDecNonce', [])]
            otf_version = self._parse_hex(info.get('OtfDecVersion', '0'))
            otf_region = info.get('OtfDecRegion', 0)
            otf_start = self._parse_hex(info.get('OtfDecStart', '0'))
            otf_end = self._parse_hex(info.get('OtfDecEnd', '0'))

            if otf_key and otf_nonce:
                self.otf_dec.configure(
                    key=otf_key,
                    nonce=otf_nonce,
                    version=otf_version,
                    region=otf_region,
                    start=otf_start,
                    end=otf_end
                )

            # Parse AES-GCM parameters
            gcm_key = [self._parse_hex(x) for x in info.get('AesGcmKey', [])]
            gcm_iv = [self._parse_hex(x) for x in info.get('AesGcmIv', [])]
            gcm_base = self._parse_hex(info.get('AesGcmBase', '0'))
            gcm_region_len = self._parse_hex(info.get('AesGcmRegionLength', '0'))
            gcm_data_len = self._parse_hex(info.get('AesGcmDataLength', '0'))

            if gcm_key and gcm_iv:
                self.aes_gcm.configure(
                    key=gcm_key,
                    iv=gcm_iv,
                    base=gcm_base,
                    region_length=gcm_region_len,
                    data_length=gcm_data_len
                )

            return True

        except (KeyError, ValueError) as e:
            print(f"[EXT_FLASH] Error parsing key info: {e}")
            return False

    @staticmethod
    def _parse_hex(value):
        """Парсить hex строку ('0x1234') или число."""
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value, 0)
        return 0

    def is_decrypted(self):
        """Проверить, загружен ли расшифрованный дамп."""
        return self._decrypted

    def get_info(self):
        """Информация для отладки."""
        lines = ["=== External Flash ==="]
        lines.append(f"  Base: 0x{self.BASE_ADDRESS:08X}")
        lines.append(f"  Size: {self.SIZE // 1024}KB")
        lines.append(f"  Decrypted: {self._decrypted}")
        lines.append(f"  OTF Dec enabled: {self.otf_dec.enabled}")
        if self.otf_dec.enabled:
            lines.append(f"    Region: 0x{self.otf_dec.start_addr:08X}"
                         f"-0x{self.otf_dec.end_addr:08X}")
        lines.append(f"  AES-GCM enabled: {self.aes_gcm.enabled}")
        if self.aes_gcm.enabled:
            lines.append(f"    Base: 0x{self.aes_gcm.base_addr:08X}")
            lines.append(f"    Region: {self.aes_gcm.region_length} bytes")

        # Первые 16 байт для проверки
        preview = ' '.join(f'{b:02X}' for b in self._data[:16])
        lines.append(f"  First 16 bytes: {preview}")

        return '\n'.join(lines)

    def __repr__(self):
        status = "decrypted" if self._decrypted else "encrypted"
        return f"ExternalFlash(0x{self.BASE_ADDRESS:08X}, {self.SIZE // 1024}KB, {status})"

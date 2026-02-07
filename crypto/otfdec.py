"""
OTF (On-The-Fly) Decryption — AES-CTR / AES-GCM

STM32H7B0 имеет аппаратный OTF декриптор, который прозрачно
расшифровывает данные из external flash при memory-mapped чтении.

Два режима:
1. AES-CTR (OTFDEC): основной регион 0x90000000-0x900FDFFF
   - 128-bit AES ключ
   - 64-bit nonce
   - 16-bit version
   - Регион (start/end адреса)
   - Счётчик формируется из адреса

2. AES-GCM: малый регион 0x900FE000-0x900FEFFF
   - 128-bit AES ключ  
   - 96-bit IV
   - Используется для защиты критических данных

Ключи и параметры берутся из (Key Info).json.

Зависимость: pycryptodome (pip install pycryptodome)
Если библиотека недоступна, используется passthrough (данные без расшифровки).
"""

import struct

# Попытка импорта AES
try:
    from Crypto.Cipher import AES
    HAS_CRYPTO = True
except ImportError:
    try:
        from Cryptodome.Cipher import AES
        HAS_CRYPTO = True
    except ImportError:
        HAS_CRYPTO = False
        print("[CRYPTO] WARNING: pycryptodome not found. "
              "OTF decryption disabled. Install with: pip install pycryptodome")
        print("[CRYPTO] Using decrypted flash image instead (external_flash_decrypted.bin)")


class AESCTRDecryptor:
    """
    AES-128-CTR декриптор для OTFDEC региона.
    
    STM32H7B0 OTFDEC формирует CTR counter block из:
    - Nonce (64 бит)
    - Version (16 бит)  
    - Region number (2 бита)
    - Адрес блока (46 бит, сдвинутый)
    
    Формат counter block (128 бит):
    [127:64] = Nonce
    [63:48]  = Version
    [47:46]  = Region
    [45:4]   = Block address >> 4 (выровнен по 16 байт)
    [3:0]    = Block counter (0 для первого блока)
    """

    def __init__(self):
        self.enabled = False
        self.key = None          # bytes (16)
        self.nonce = None        # bytes (8)
        self.version = 0         # uint16
        self.region = 0          # uint8 (0-3)
        self.start_addr = 0      # Start of encrypted region
        self.end_addr = 0        # End of encrypted region

    def configure(self, key_words, nonce_words, version, region, start, end):
        """
        Настроить декриптор.
        
        key_words: list of 4 uint32 (AES-128 key)
        nonce_words: list of 2 uint32 (64-bit nonce)
        version: uint16
        region: 0-3
        start: start address
        end: end address
        """
        if not HAS_CRYPTO:
            self.enabled = False
            return

        if not key_words or len(key_words) < 4:
            self.enabled = False
            return

        # Конвертировать uint32 слова в bytes (big-endian для AES key)
        self.key = struct.pack('>IIII',
                               key_words[0], key_words[1],
                               key_words[2], key_words[3])

        if nonce_words and len(nonce_words) >= 2:
            self.nonce = struct.pack('>II', nonce_words[0], nonce_words[1])
        else:
            self.nonce = b'\x00' * 8

        self.version = version & 0xFFFF
        self.region = region & 0x3
        self.start_addr = start
        self.end_addr = end
        self.enabled = True

        print(f"[OTFDEC] Configured: region={region}, "
              f"0x{start:08X}-0x{end:08X}, "
              f"key={self.key.hex()}")

    def is_in_region(self, address):
        """Проверить, попадает ли адрес в зашифрованный регион."""
        if not self.enabled:
            return False
        return self.start_addr <= address <= self.end_addr

    def _build_counter_block(self, address):
        """
        Построить начальный counter block для данного адреса.
        
        Формат (128 бит, big-endian):
        Nonce[63:0] | Version[15:0] | Region[1:0] | BlockAddr[45:4] | Counter[3:0]
        
        BlockAddr = (address - start_addr) >> 4, выровнен по 16-байтному блоку.
        """
        # Вычислить номер 16-байтного блока относительно начала
        block_offset = (address - self.start_addr) & ~0xF
        block_number = block_offset >> 4

        # Собрать 64-бит нижнюю часть counter block
        # [63:48] = version (16 бит)
        # [47:46] = region (2 бита)
        # [45:4]  = block_number (42 бита)
        # [3:0]   = 0 (counter start)
        lower = ((self.version & 0xFFFF) << 48) | \
                ((self.region & 0x3) << 46) | \
                ((block_number & 0x3FFFFFFFFFF) << 4)

        # Counter block = nonce (8 bytes) + lower (8 bytes)
        counter = self.nonce + struct.pack('>Q', lower)
        return counter

    def decrypt(self, address, encrypted_data):
        """
        Расшифровать данные начиная с address.
        
        address: начальный адрес (должен быть в регионе)
        encrypted_data: bytes с зашифрованными данными
        
        Возвращает bytes с расшифрованными данными.
        """
        if not self.enabled or not HAS_CRYPTO:
            return encrypted_data

        if not self.is_in_region(address):
            return encrypted_data

        # Выровнять адрес по 16 байт
        aligned_addr = address & ~0xF
        offset_in_block = address - aligned_addr

        # Если данные не выровнены, нужно расшифровать с начала блока
        if offset_in_block > 0:
            # Дополнить данные спереди нулями для выравнивания
            padded = bytes(offset_in_block) + encrypted_data
        else:
            padded = encrypted_data

        # Построить counter block
        initial_counter = self._build_counter_block(aligned_addr)

        try:
            cipher = AES.new(self.key, AES.MODE_CTR,
                             nonce=b'',
                             initial_value=initial_counter)
            decrypted = cipher.decrypt(padded)

            # Убрать padding если был
            if offset_in_block > 0:
                return decrypted[offset_in_block:offset_in_block + len(encrypted_data)]
            return decrypted[:len(encrypted_data)]

        except Exception as e:
            print(f"[OTFDEC] Decrypt error at 0x{address:08X}: {e}")
            return encrypted_data

    def decrypt_word(self, address, encrypted_word):
        """Расшифровать одно 32-битное слово."""
        data = struct.pack('<I', encrypted_word)
        decrypted = self.decrypt(address, data)
        return struct.unpack('<I', decrypted)[0]

    def __repr__(self):
        if self.enabled:
            return (f"AESCTRDecryptor(0x{self.start_addr:08X}-"
                    f"0x{self.end_addr:08X})")
        return "AESCTRDecryptor(disabled)"


class AESGCMDecryptor:
    """
    AES-128-GCM декриптор для малого региона external flash.
    
    Используется для защиты небольшого блока данных
    (обычно 0x40 байт) в конце flash.
    """

    def __init__(self):
        self.enabled = False
        self.key = None          # bytes (16)
        self.iv = None           # bytes (12)
        self.base_addr = 0       # Base address
        self.region_length = 0   # Length of region
        self.data_length = 0     # Length of actual data

        self._decrypted_cache = None

    def configure(self, key_words, iv_words, base, region_length, data_length):
        """
        Настроить GCM декриптор.
        
        key_words: list of 4 uint32
        iv_words: list of 3 uint32 (96-bit IV)
        base: base address
        region_length: size of region
        data_length: size of actual encrypted data
        """
        if not HAS_CRYPTO:
            self.enabled = False
            return

        if not key_words or len(key_words) < 4:
            self.enabled = False
            return

        self.key = struct.pack('>IIII',
                               key_words[0], key_words[1],
                               key_words[2], key_words[3])

        if iv_words and len(iv_words) >= 3:
            self.iv = struct.pack('>III', iv_words[0], iv_words[1], iv_words[2])
        else:
            self.iv = b'\x00' * 12

        self.base_addr = base
        self.region_length = region_length
        self.data_length = data_length
        self.enabled = True
        self._decrypted_cache = None

        print(f"[AES-GCM] Configured: 0x{base:08X}, "
              f"region={region_length}, data={data_length}")

    def is_in_region(self, address):
        """Проверить, попадает ли адрес в GCM регион."""
        if not self.enabled:
            return False
        return self.base_addr <= address < self.base_addr + self.region_length

    def decrypt_region(self, encrypted_data):
        """
        Расшифровать весь GCM регион.
        
        encrypted_data: bytes — зашифрованные данные региона
        
        Возвращает bytes с расшифрованными данными.
        Результат кэшируется.
        """
        if not self.enabled or not HAS_CRYPTO:
            return encrypted_data

        if self._decrypted_cache is not None:
            return self._decrypted_cache

        try:
            # В GCM данные = ciphertext + tag
            # data_length = размер полезных данных
            # Последние 16 байт могут быть tag
            actual_data = encrypted_data[:self.data_length]

            cipher = AES.new(self.key, AES.MODE_GCM, nonce=self.iv)
            decrypted = cipher.decrypt(actual_data)

            # Кэшировать результат
            self._decrypted_cache = decrypted
            return decrypted

        except Exception as e:
            print(f"[AES-GCM] Decrypt error: {e}")
            return encrypted_data

    def decrypt(self, address, encrypted_data):
        """Расшифровать данные по адресу из GCM региона."""
        if not self.enabled or not HAS_CRYPTO:
            return encrypted_data

        # Для GCM обычно расшифровываем весь регион сразу
        # и потом читаем по offset
        return encrypted_data  # Simplified: passthrough

    def __repr__(self):
        if self.enabled:
            return (f"AESGCMDecryptor(0x{self.base_addr:08X}, "
                    f"len={self.data_length})")
        return "AESGCMDecryptor(disabled)"


class OTFDecryption:
    """
    Главный класс OTF декриптирования.
    
    Объединяет AES-CTR (OTFDEC) и AES-GCM декрипторы.
    Предоставляет единый интерфейс для external_flash.py.
    """

    def __init__(self):
        self.ctr = AESCTRDecryptor()
        self.gcm = AESGCMDecryptor()

    def configure_from_key_info(self, key_info):
        """
        Настроить из словаря (загруженного из (Key Info).json).
        
        key_info: dict с ключами:
            OtfDecKey, OtfDecNonce, OtfDecVersion, OtfDecRegion,
            OtfDecStart, OtfDecEnd,
            AesGcmKey, AesGcmIv, AesGcmBase,
            AesGcmRegionLength, AesGcmDataLength
        """
        # CTR
        otf_key = [self._parse_hex(x) for x in key_info.get('OtfDecKey', [])]
        otf_nonce = [self._parse_hex(x) for x in key_info.get('OtfDecNonce', [])]
        otf_version = self._parse_hex(key_info.get('OtfDecVersion', '0'))
        otf_region = key_info.get('OtfDecRegion', 0)
        otf_start = self._parse_hex(key_info.get('OtfDecStart', '0'))
        otf_end = self._parse_hex(key_info.get('OtfDecEnd', '0'))

        if otf_key:
            self.ctr.configure(otf_key, otf_nonce, otf_version,
                               otf_region, otf_start, otf_end)

        # GCM
        gcm_key = [self._parse_hex(x) for x in key_info.get('AesGcmKey', [])]
        gcm_iv = [self._parse_hex(x) for x in key_info.get('AesGcmIv', [])]
        gcm_base = self._parse_hex(key_info.get('AesGcmBase', '0'))
        gcm_region_len = self._parse_hex(key_info.get('AesGcmRegionLength', '0'))
        gcm_data_len = self._parse_hex(key_info.get('AesGcmDataLength', '0'))

        if gcm_key:
            self.gcm.configure(gcm_key, gcm_iv, gcm_base,
                               gcm_region_len, gcm_data_len)

    def decrypt(self, address, data):
        """
        Расшифровать данные по адресу.
        Автоматически выбирает CTR или GCM.
        """
        if self.ctr.is_in_region(address):
            return self.ctr.decrypt(address, data)
        if self.gcm.is_in_region(address):
            return self.gcm.decrypt(address, data)
        return data

    def is_encrypted_region(self, address):
        """Проверить, является ли адрес зашифрованным."""
        return self.ctr.is_in_region(address) or self.gcm.is_in_region(address)

    @property
    def available(self):
        """Доступно ли аппаратное шифрование."""
        return HAS_CRYPTO

    @staticmethod
    def _parse_hex(value):
        """Разобрать hex строку или int."""
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value, 0)
        return 0

    def __repr__(self):
        return f"OTFDecryption(CTR={self.ctr}, GCM={self.gcm})"

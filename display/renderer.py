"""
Display Renderer — pygame-based 320x240 screen

Читает фреймбуфер из RAM эмулятора и отображает в окне pygame.
Поддерживает форматы пикселей LTDC:
  0: ARGB8888 (4 байта)
  1: RGB888   (3 байта)
  2: RGB565   (2 байта)
  3: ARGB1555 (2 байта)
  4: ARGB4444 (2 байта)
  5: L8       (1 байт — grayscale)

Game & Watch использует RGB565 (формат 2).

Окно масштабируется для удобного просмотра (2x или 3x).
"""

import struct
import time

try:
    import pygame
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False
    print("[DISPLAY] WARNING: pygame not found. Install with: pip install pygame")
    print("[DISPLAY] Display will be disabled.")


class DisplayRenderer:
    """
    Рендерер дисплея Game & Watch.
    
    Читает фреймбуфер из системной шины и отображает через pygame.
    """

    # Game & Watch native resolution
    NATIVE_WIDTH = 320
    NATIVE_HEIGHT = 240

    # Pixel format constants (matching LTDC PFCR)
    FMT_ARGB8888 = 0
    FMT_RGB888   = 1
    FMT_RGB565   = 2
    FMT_ARGB1555 = 3
    FMT_ARGB4444 = 4
    FMT_L8       = 5
    FMT_AL44     = 6
    FMT_AL88     = 7

    def __init__(self, scale=2, title="Game & Watch Emulator"):
        """
        scale: множитель масштабирования окна (1, 2, 3)
        title: заголовок окна
        """
        self.scale = scale
        self.title = title
        self.width = self.NATIVE_WIDTH
        self.height = self.NATIVE_HEIGHT

        self._initialized = False
        self._screen = None
        self._surface = None    # Native resolution surface
        self._clock = None

        # Framebuffer info (от LTDC)
        self._fb_address = 0
        self._fb_format = self.FMT_RGB565
        self._fb_pitch = 0      # Bytes per line

        # FPS tracking
        self._frame_count = 0
        self._fps = 0.0
        self._fps_timer = 0.0

        # Bus reference для чтения фреймбуфера
        self._bus = None

    def init(self, bus=None):
        """
        Инициализировать pygame и создать окно.
        
        bus: SystemBus для чтения фреймбуфера из RAM.
        """
        self._bus = bus

        if not HAS_PYGAME:
            print("[DISPLAY] pygame unavailable, display disabled")
            return False

        try:
            pygame.init()
            
            window_w = self.width * self.scale
            window_h = self.height * self.scale

            self._screen = pygame.display.set_mode((window_w, window_h))
            pygame.display.set_caption(self.title)

            # Surface для рисования в native resolution
            self._surface = pygame.Surface((self.width, self.height))
            self._surface.fill((0, 0, 0))

            self._clock = pygame.time.Clock()
            self._fps_timer = time.time()
            self._initialized = True

            print(f"[DISPLAY] Initialized: {self.width}x{self.height} "
                  f"(window: {window_w}x{window_h})")
            return True

        except Exception as e:
            print(f"[DISPLAY] Init failed: {e}")
            self._initialized = False
            return False

    def shutdown(self):
        """Закрыть pygame."""
        if self._initialized and HAS_PYGAME:
            pygame.quit()
            self._initialized = False

    @property
    def is_active(self):
        return self._initialized

    # =============================================================
    # Framebuffer configuration
    # =============================================================

    def set_framebuffer(self, address, pixel_format=FMT_RGB565, pitch=0):
        """
        Установить параметры фреймбуфера.
        
        address: адрес фреймбуфера в памяти
        pixel_format: формат пикселей (0-7)
        pitch: байт на строку (0 = автовычисление)
        """
        self._fb_address = address
        self._fb_format = pixel_format

        if pitch == 0:
            bpp = self._bytes_per_pixel(pixel_format)
            self._fb_pitch = self.width * bpp
        else:
            self._fb_pitch = pitch

    def configure_from_ltdc(self, ltdc):
        """
        Автоконфигурация из LTDC peripheral.
        
        ltdc: экземпляр peripherals.ltdc.LTDC
        """
        info = ltdc.get_framebuffer_info()
        if info is None:
            return

        self._fb_address = info['address']
        self._fb_format = info['pixel_format']

        line_length, pitch = info['line_length']
        if pitch > 0:
            self._fb_pitch = pitch
        elif line_length > 0:
            self._fb_pitch = line_length
        else:
            bpp = self._bytes_per_pixel(self._fb_format)
            self._fb_pitch = self.width * bpp

        # Обновить размер дисплея из LTDC
        w, h = ltdc.get_display_size()
        if 0 < w <= 1024 and 0 < h <= 1024:
            self.width = w
            self.height = h

    # =============================================================
    # Frame rendering
    # =============================================================

    def render_frame(self):
        """
        Отрисовать один кадр.
        
        Читает фреймбуфер из памяти, конвертирует пиксели,
        отображает в окне.
        
        Возвращает True если кадр отрисован успешно.
        """
        if not self._initialized:
            return False

        if self._bus is None or self._fb_address == 0:
            # Нет фреймбуфера — чёрный экран
            self._surface.fill((0, 0, 0))
            self._present()
            return True

        try:
            self._read_and_draw_framebuffer()
            self._present()
            self._update_fps()
            return True
        except Exception as e:
            # Не падаем при ошибках рендеринга
            return False

    def _read_and_draw_framebuffer(self):
        """Прочитать фреймбуфер из памяти и нарисовать на surface."""
        bus = self._bus
        fb_addr = self._fb_address
        fmt = self._fb_format
        pitch = self._fb_pitch
        w = self.width
        h = self.height
        bpp = self._bytes_per_pixel(fmt)

        # Pixel array для быстрого заполнения
        pixels = pygame.PixelArray(self._surface)

        for y in range(h):
            line_addr = fb_addr + y * pitch

            for x in range(w):
                pixel_addr = line_addr + x * bpp
                r, g, b = self._read_pixel(bus, pixel_addr, fmt)
                pixels[x, y] = (r, g, b)

        # Освободить pixel array
        del pixels

    def _read_pixel(self, bus, address, fmt):
        """
        Прочитать один пиксель из памяти.
        
        Возвращает (R, G, B) в диапазоне 0-255.
        """
        if fmt == self.FMT_RGB565:
            val = bus.read16(address)
            return self._decode_rgb565(val)

        elif fmt == self.FMT_ARGB8888:
            val = bus.read32(address)
            return self._decode_argb8888(val)

        elif fmt == self.FMT_RGB888:
            b = bus.read8(address)
            g = bus.read8(address + 1)
            r = bus.read8(address + 2)
            return (r, g, b)

        elif fmt == self.FMT_ARGB1555:
            val = bus.read16(address)
            return self._decode_argb1555(val)

        elif fmt == self.FMT_ARGB4444:
            val = bus.read16(address)
            return self._decode_argb4444(val)

        elif fmt == self.FMT_L8:
            val = bus.read8(address)
            return (val, val, val)

        # Fallback
        return (0, 0, 0)

    # =============================================================
    # Optimized rendering (batch read)
    # =============================================================

    def render_frame_fast(self):
        """
        Быстрый рендеринг — читает строки целиком.
        Используется когда фреймбуфер в непрерывной RAM.
        """
        if not self._initialized:
            return False

        if self._bus is None or self._fb_address == 0:
            self._surface.fill((0, 0, 0))
            self._present()
            return True

        try:
            self._read_framebuffer_fast()
            self._present()
            self._update_fps()
            return True
        except Exception:
            return False

    def _read_framebuffer_fast(self):
        """Быстрое чтение — через SRAM напрямую."""
        bus = self._bus
        fb_addr = self._fb_address
        fmt = self._fb_format
        pitch = self._fb_pitch
        w = self.width
        h = self.height
        bpp = self._bytes_per_pixel(fmt)

        # Попробовать найти RAM регион для batch read
        sram = bus.sram
        region = sram._find_region(fb_addr)

        if region is None:
            # Fallback на медленный метод
            self._read_and_draw_framebuffer()
            return

        pixels = pygame.PixelArray(self._surface)

        for y in range(h):
            line_addr = fb_addr + y * pitch

            try:
                line_data = region.read_block(line_addr, w * bpp)
            except (MemoryError, Exception):
                continue

            for x in range(w):
                offset = x * bpp

                if fmt == self.FMT_RGB565:
                    if offset + 2 <= len(line_data):
                        val = struct.unpack_from('<H', line_data, offset)[0]
                        r, g, b = self._decode_rgb565(val)
                        pixels[x, y] = (r, g, b)

                elif fmt == self.FMT_ARGB8888:
                    if offset + 4 <= len(line_data):
                        val = struct.unpack_from('<I', line_data, offset)[0]
                        r, g, b = self._decode_argb8888(val)
                        pixels[x, y] = (r, g, b)

                elif fmt == self.FMT_L8:
                    if offset < len(line_data):
                        v = line_data[offset]
                        pixels[x, y] = (v, v, v)

        del pixels

    # =============================================================
    # Pixel format decoders
    # =============================================================

    @staticmethod
    def _decode_rgb565(val):
        """RGB565: RRRRRGGGGGGBBBBB → (R8, G8, B8)"""
        r5 = (val >> 11) & 0x1F
        g6 = (val >> 5) & 0x3F
        b5 = val & 0x1F
        # Расширить до 8 бит
        r = (r5 << 3) | (r5 >> 2)
        g = (g6 << 2) | (g6 >> 4)
        b = (b5 << 3) | (b5 >> 2)
        return (r, g, b)

    @staticmethod
    def _decode_argb8888(val):
        """ARGB8888: AAAAAAAARRRRRRRRGGGGGGGGBBBBBBBB"""
        r = (val >> 16) & 0xFF
        g = (val >> 8) & 0xFF
        b = val & 0xFF
        return (r, g, b)

    @staticmethod
    def _decode_argb1555(val):
        """ARGB1555: ARRRRRGGGGGBBBBB"""
        r5 = (val >> 10) & 0x1F
        g5 = (val >> 5) & 0x1F
        b5 = val & 0x1F
        r = (r5 << 3) | (r5 >> 2)
        g = (g5 << 3) | (g5 >> 2)
        b = (b5 << 3) | (b5 >> 2)
        return (r, g, b)

    @staticmethod
    def _decode_argb4444(val):
        """ARGB4444: AAAARRRRGGGBBBB"""
        r4 = (val >> 8) & 0xF
        g4 = (val >> 4) & 0xF
        b4 = val & 0xF
        r = (r4 << 4) | r4
        g = (g4 << 4) | g4
        b = (b4 << 4) | b4
        return (r, g, b)

    @staticmethod
    def _bytes_per_pixel(fmt):
        """Размер пикселя в байтах."""
        sizes = {0: 4, 1: 3, 2: 2, 3: 2, 4: 2, 5: 1, 6: 1, 7: 2}
        return sizes.get(fmt, 2)

    # =============================================================
    # Presentation
    # =============================================================

    def _present(self):
        """Вывести surface на экран (с масштабированием)."""
        if self.scale == 1:
            self._screen.blit(self._surface, (0, 0))
        else:
            scaled = pygame.transform.scale(
                self._surface,
                (self.width * self.scale, self.height * self.scale)
            )
            self._screen.blit(scaled, (0, 0))

        pygame.display.flip()

    def _update_fps(self):
        """Обновить счётчик FPS."""
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._fps_timer

        if elapsed >= 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_timer = now
            pygame.display.set_caption(
                f"{self.title} - {self._fps:.1f} FPS"
            )

    # =============================================================
    # Manual drawing (для отладки)
    # =============================================================

    def fill(self, r, g, b):
        """Залить экран цветом."""
        if self._initialized:
            self._surface.fill((r, g, b))
            self._present()

    def draw_test_pattern(self):
        """Нарисовать тестовый паттерн."""
        if not self._initialized:
            return

        for y in range(self.height):
            for x in range(self.width):
                r = (x * 255) // self.width
                g = (y * 255) // self.height
                b = 128
                self._surface.set_at((x, y), (r, g, b))

        self._present()

    def show_text(self, text, x=10, y=10, color=(255, 255, 255)):
        """Показать текст на экране (для отладки)."""
        if not self._initialized:
            return
        try:
            font = pygame.font.SysFont('monospace', 14)
            text_surface = font.render(text, True, color)
            self._surface.blit(text_surface, (x, y))
        except Exception:
            pass

    # =============================================================
    # Event processing
    # =============================================================

    def process_events(self):
        """
        Обработать события pygame.
        
        Возвращает False если окно закрыто (нужно выйти).
        """
        if not self._initialized:
            return True

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False

        return True

    def get_pressed_keys(self):
        """Получить словарь нажатых клавиш."""
        if not self._initialized:
            return {}
        return pygame.key.get_pressed()

    def limit_fps(self, target_fps=60):
        """Ограничить FPS."""
        if self._clock:
            self._clock.tick(target_fps)

    # =============================================================
    # Info
    # =============================================================

    @property
    def fps(self):
        return self._fps

    def __repr__(self):
        if self._initialized:
            return (f"Display({self.width}x{self.height}, "
                    f"scale={self.scale}, "
                    f"fb=0x{self._fb_address:08X}, "
                    f"fps={self._fps:.1f})")
        return "Display(not initialized)"

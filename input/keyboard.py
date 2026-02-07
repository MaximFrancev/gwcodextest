"""
Keyboard Controller — маппинг клавиатуры на GPIO пины Game & Watch.

Из документации (docs/Buttons.md):

| STM32 Pin | Button     | GPIO Port | Pin |
|-----------|------------|-----------|-----|
| PD11      | Left       | D         | 11  |
| PD0       | Up         | D         | 0   |
| PD14      | Down       | D         | 14  |
| PD15      | Right      | D         | 15  |
| PD9       | A          | D         | 9   |
| PD5       | B          | D         | 5   |
| PC1       | Game       | C         | 1   |
| PC4       | Time       | C         | 4   |
| PC13      | Pause/Set  | C         | 13  |
| PA0       | Power      | A         | 0   |

Кнопки active-low: нажатие = 0, отпущено = 1 (pull-up).

Маппинг клавиатуры по умолчанию:
  Arrow keys  → D-pad (Left/Up/Down/Right)
  Z / X       → A / B
  Enter       → Game
  T           → Time
  P / Space   → Pause/Set
  Backspace   → Power
"""

try:
    import pygame
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False


class ButtonMapping:
    """Описание одной кнопки: клавиша → GPIO порт + пин."""

    __slots__ = ['name', 'port', 'pin', 'keys']

    def __init__(self, name, port, pin, keys):
        """
        name: имя кнопки ("Left", "A", etc.)
        port: буква GPIO порта ('A', 'B', 'C', 'D', 'E')
        pin: номер пина (0-15)
        keys: список pygame key constants
        """
        self.name = name
        self.port = port
        self.pin = pin
        self.keys = keys  # list of pygame.K_xxx

    def __repr__(self):
        return f"Button({self.name}: GPIO{self.port}{self.pin})"


# ================================================================
# Default keyboard layout
# ================================================================

def _default_mappings():
    """
    Создать маппинг по умолчанию.
    Возвращает список ButtonMapping.
    
    Вызывается после инициализации pygame (нужны константы K_*).
    """
    if not HAS_PYGAME:
        return []

    return [
        # D-pad
        ButtonMapping("Left",      'D', 11, [pygame.K_LEFT]),
        ButtonMapping("Up",        'D', 0,  [pygame.K_UP]),
        ButtonMapping("Down",      'D', 14, [pygame.K_DOWN]),
        ButtonMapping("Right",     'D', 15, [pygame.K_RIGHT]),

        # Action buttons
        ButtonMapping("A",         'D', 9,  [pygame.K_z, pygame.K_j]),
        ButtonMapping("B",         'D', 5,  [pygame.K_x, pygame.K_k]),

        # System buttons
        ButtonMapping("Game",      'C', 1,  [pygame.K_RETURN, pygame.K_g]),
        ButtonMapping("Time",      'C', 4,  [pygame.K_t]),
        ButtonMapping("Pause/Set", 'C', 13, [pygame.K_p, pygame.K_SPACE]),
        ButtonMapping("Power",     'A', 0,  [pygame.K_BACKSPACE, pygame.K_ESCAPE]),
    ]


class KeyboardController:
    """
    Контроллер ввода: читает состояние клавиатуры через pygame
    и обновляет GPIO пины эмулятора.
    
    Кнопки Game & Watch — active-low (нажато = LOW = 0).
    GPIO порты по умолчанию pull-up (отпущено = HIGH = 1).
    
    Использование:
        kb = KeyboardController(gpio)
        kb.init()
        
        # В главном цикле:
        kb.update()
    """

    def __init__(self, gpio=None):
        """
        gpio: peripherals.gpio.GPIO — контроллер GPIO портов.
              Может быть установлен позже через set_gpio().
        """
        self._gpio = gpio
        self._mappings = []
        self._initialized = False

        # Состояние каждой кнопки (True = нажата)
        self._button_state = {}

        # Callback при нажатии/отпускании (для отладки)
        self.on_button_change = None

        # Trace
        self.trace_enabled = False

    def set_gpio(self, gpio):
        """Установить GPIO контроллер."""
        self._gpio = gpio

    def init(self, custom_mappings=None):
        """
        Инициализировать маппинг.
        
        custom_mappings: список ButtonMapping для замены дефолтного.
                        Если None — используется дефолтный маппинг.
        
        Должен вызываться ПОСЛЕ pygame.init().
        """
        if not HAS_PYGAME:
            print("[INPUT] WARNING: pygame not available, keyboard disabled")
            return False

        if custom_mappings:
            self._mappings = custom_mappings
        else:
            self._mappings = _default_mappings()

        # Инициализировать состояния
        for btn in self._mappings:
            self._button_state[btn.name] = False

        # Установить все кнопки в отпущенное состояние (HIGH)
        self._release_all()

        self._initialized = True

        if self.trace_enabled:
            print(f"[INPUT] Initialized with {len(self._mappings)} buttons:")
            for btn in self._mappings:
                key_names = [pygame.key.name(k) for k in btn.keys]
                print(f"  {btn.name:12s} -> GPIO{btn.port}{btn.pin:2d}"
                      f"  keys: {', '.join(key_names)}")

        return True

    def _release_all(self):
        """Установить все кнопки в отпущенное состояние (HIGH = 1)."""
        if self._gpio is None:
            return
        for btn in self._mappings:
            self._gpio.set_pin(btn.port, btn.pin, True)  # HIGH = released

    def update(self):
        """
        Обновить состояние GPIO на основе текущих нажатых клавиш.
        
        Вызывать каждый кадр (после pygame event processing).
        
        Возвращает dict {button_name: is_pressed} с изменениями,
        или пустой dict если ничего не изменилось.
        """
        if not self._initialized or not HAS_PYGAME:
            return {}

        keys = pygame.key.get_pressed()
        changes = {}

        for btn in self._mappings:
            # Проверить, нажата ли хотя бы одна из назначенных клавиш
            pressed = any(keys[k] for k in btn.keys)

            # Обнаружить изменение
            old_state = self._button_state.get(btn.name, False)
            if pressed != old_state:
                self._button_state[btn.name] = pressed
                changes[btn.name] = pressed

                # Обновить GPIO: active-low → нажато = LOW (False)
                if self._gpio is not None:
                    self._gpio.set_pin(btn.port, btn.pin, not pressed)

                if self.trace_enabled:
                    state_str = "PRESSED" if pressed else "RELEASED"
                    print(f"[INPUT] {btn.name:12s} {state_str}"
                          f" (GPIO{btn.port}{btn.pin} = {'LOW' if pressed else 'HIGH'})")

                if self.on_button_change:
                    self.on_button_change(btn.name, pressed)

        return changes

    def update_from_events(self, events):
        """
        Альтернативный метод: обновление из списка pygame событий.
        Более точный, обрабатывает каждое нажатие/отпускание.
        
        events: список pygame.event из pygame.event.get()
        """
        if not self._initialized or not HAS_PYGAME:
            return {}

        changes = {}

        for event in events:
            if event.type == pygame.KEYDOWN:
                for btn in self._mappings:
                    if event.key in btn.keys:
                        if not self._button_state.get(btn.name, False):
                            self._button_state[btn.name] = True
                            changes[btn.name] = True

                            if self._gpio is not None:
                                self._gpio.set_pin(btn.port, btn.pin, False)  # LOW

                            if self.trace_enabled:
                                print(f"[INPUT] {btn.name} PRESSED")

            elif event.type == pygame.KEYUP:
                for btn in self._mappings:
                    if event.key in btn.keys:
                        # Проверить, что все назначенные клавиши отпущены
                        keys = pygame.key.get_pressed()
                        still_pressed = any(keys[k] for k in btn.keys)
                        if not still_pressed:
                            self._button_state[btn.name] = False
                            changes[btn.name] = False

                            if self._gpio is not None:
                                self._gpio.set_pin(btn.port, btn.pin, True)  # HIGH

                            if self.trace_enabled:
                                print(f"[INPUT] {btn.name} RELEASED")

        if changes and self.on_button_change:
            for name, pressed in changes.items():
                self.on_button_change(name, pressed)

        return changes

    # ================================================================
    # Query state
    # ================================================================

    def is_pressed(self, button_name):
        """Проверить, нажата ли кнопка по имени."""
        return self._button_state.get(button_name, False)

    def get_all_pressed(self):
        """Получить список всех нажатых кнопок."""
        return [name for name, pressed in self._button_state.items() if pressed]

    def get_state(self):
        """Получить полное состояние всех кнопок."""
        return dict(self._button_state)

    @property
    def any_pressed(self):
        """True если хотя бы одна кнопка нажата."""
        return any(self._button_state.values())

    # ================================================================
    # Remapping
    # ================================================================

    def remap_button(self, button_name, new_keys):
        """
        Переназначить клавиши для кнопки.
        
        button_name: "Left", "A", "Game", etc.
        new_keys: список pygame.K_xxx
        """
        for btn in self._mappings:
            if btn.name == button_name:
                btn.keys = new_keys
                if self.trace_enabled:
                    if HAS_PYGAME:
                        names = [pygame.key.name(k) for k in new_keys]
                    else:
                        names = [str(k) for k in new_keys]
                    print(f"[INPUT] Remapped {button_name} -> {', '.join(names)}")
                return True
        return False

    def add_key(self, button_name, key):
        """Добавить дополнительную клавишу к кнопке."""
        for btn in self._mappings:
            if btn.name == button_name:
                if key not in btn.keys:
                    btn.keys.append(key)
                return True
        return False

    # ================================================================
    # Programmatic button press (для тестов / автоматизации)
    # ================================================================

    def press_button(self, button_name):
        """Программно нажать кнопку."""
        for btn in self._mappings:
            if btn.name == button_name:
                self._button_state[btn.name] = True
                if self._gpio is not None:
                    self._gpio.set_pin(btn.port, btn.pin, False)  # LOW = pressed
                return True
        return False

    def release_button(self, button_name):
        """Программно отпустить кнопку."""
        for btn in self._mappings:
            if btn.name == button_name:
                self._button_state[btn.name] = False
                if self._gpio is not None:
                    self._gpio.set_pin(btn.port, btn.pin, True)  # HIGH = released
                return True
        return False

    # ================================================================
    # Info
    # ================================================================

    def get_mapping_info(self):
        """Получить информацию о текущем маппинге."""
        lines = ["=== Keyboard Mapping ==="]
        for btn in self._mappings:
            if HAS_PYGAME:
                key_names = [pygame.key.name(k) for k in btn.keys]
            else:
                key_names = [str(k) for k in btn.keys]
            state = "PRESSED" if self._button_state.get(btn.name) else "released"
            lines.append(
                f"  {btn.name:12s} GPIO{btn.port}{btn.pin:2d}"
                f"  [{', '.join(key_names):20s}]  {state}"
            )
        return '\n'.join(lines)

    @property
    def is_active(self):
        return self._initialized

    def __repr__(self):
        n = len(self._mappings)
        pressed = len(self.get_all_pressed())
        return f"KeyboardController({n} buttons, {pressed} pressed)"

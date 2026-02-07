"""
Logger — логирование для отладки эмулятора.

Поддерживает уровни: ERROR, WARN, INFO, DEBUG, TRACE.
Вывод в консоль и опционально в файл.
Можно включать/выключать по подсистемам (CPU, BUS, GPU, etc.).
"""

import sys
import time
from enum import IntEnum


class LogLevel(IntEnum):
    """Уровни логирования."""
    NONE  = 0
    ERROR = 1
    WARN  = 2
    INFO  = 3
    DEBUG = 4
    TRACE = 5


class Logger:
    """
    Логгер эмулятора.
    
    Использование:
        log = Logger(level=LogLevel.INFO)
        log.info("CPU", "Reset complete")
        log.debug("BUS", f"Read 0x{addr:08X} = 0x{val:08X}")
        
        # Включить/выключить подсистемы
        log.enable("CPU")
        log.disable("BUS")
    """

    # Цвета для терминала (ANSI)
    _COLORS = {
        LogLevel.ERROR: "\033[91m",   # Red
        LogLevel.WARN:  "\033[93m",   # Yellow
        LogLevel.INFO:  "\033[92m",   # Green
        LogLevel.DEBUG: "\033[96m",   # Cyan
        LogLevel.TRACE: "\033[90m",   # Gray
    }
    _RESET = "\033[0m"

    _LEVEL_NAMES = {
        LogLevel.ERROR: "ERR",
        LogLevel.WARN:  "WRN",
        LogLevel.INFO:  "INF",
        LogLevel.DEBUG: "DBG",
        LogLevel.TRACE: "TRC",
    }

    def __init__(self, level=LogLevel.INFO, use_color=True, log_file=None):
        """
        level: минимальный уровень для вывода
        use_color: использовать ANSI цвета
        log_file: путь к файлу для записи (None = только консоль)
        """
        self.level = level
        self.use_color = use_color
        self._file = None
        self._start_time = time.time()

        # Фильтр подсистем: если пусто — выводить всё
        self._enabled_subsystems = set()
        self._disabled_subsystems = set()

        # Счётчики
        self._counts = {lvl: 0 for lvl in LogLevel if lvl != LogLevel.NONE}

        if log_file:
            try:
                self._file = open(log_file, 'w')
            except IOError as e:
                print(f"[LOGGER] Cannot open log file: {e}", file=sys.stderr)

    def close(self):
        """Закрыть файл логов."""
        if self._file:
            self._file.close()
            self._file = None

    # ================================================================
    # Фильтрация подсистем
    # ================================================================

    def enable(self, subsystem):
        """Включить вывод для подсистемы."""
        self._enabled_subsystems.add(subsystem.upper())
        self._disabled_subsystems.discard(subsystem.upper())

    def disable(self, subsystem):
        """Выключить вывод для подсистемы."""
        self._disabled_subsystems.add(subsystem.upper())
        self._enabled_subsystems.discard(subsystem.upper())

    def _is_allowed(self, subsystem):
        """Проверить, разрешён ли вывод для подсистемы."""
        sub = subsystem.upper()
        if sub in self._disabled_subsystems:
            return False
        if self._enabled_subsystems and sub not in self._enabled_subsystems:
            return False
        return True

    # ================================================================
    # Logging methods
    # ================================================================

    def log(self, level, subsystem, message):
        """Общий метод логирования."""
        if level > self.level:
            return
        if not self._is_allowed(subsystem):
            return

        self._counts[level] = self._counts.get(level, 0) + 1

        elapsed = time.time() - self._start_time
        level_name = self._LEVEL_NAMES.get(level, "???")

        line = f"[{elapsed:8.3f}] [{level_name}] [{subsystem:5s}] {message}"

        # Console
        if self.use_color and sys.stdout.isatty():
            color = self._COLORS.get(level, "")
            print(f"{color}{line}{self._RESET}")
        else:
            print(line)

        # File
        if self._file:
            self._file.write(line + '\n')
            self._file.flush()

    def error(self, subsystem, message):
        self.log(LogLevel.ERROR, subsystem, message)

    def warn(self, subsystem, message):
        self.log(LogLevel.WARN, subsystem, message)

    def info(self, subsystem, message):
        self.log(LogLevel.INFO, subsystem, message)

    def debug(self, subsystem, message):
        self.log(LogLevel.DEBUG, subsystem, message)

    def trace(self, subsystem, message):
        self.log(LogLevel.TRACE, subsystem, message)

    # ================================================================
    # Специализированные хелперы
    # ================================================================

    def cpu_state(self, regs, cycle_count=0):
        """Вывести состояние CPU (уровень TRACE)."""
        if self.level < LogLevel.TRACE:
            return
        if not self._is_allowed("CPU"):
            return
        self.trace("CPU", f"Cycle {cycle_count}: PC=0x{regs.pc:08X} "
                          f"SP=0x{regs.sp:08X} LR=0x{regs.lr:08X}")

    def mem_access(self, rw, width, addr, value):
        """Логировать обращение к памяти (уровень TRACE)."""
        if self.level < LogLevel.TRACE:
            return
        if not self._is_allowed("BUS"):
            return
        op = "R" if rw == 'r' else "W"
        self.trace("BUS", f"{op}{width} 0x{addr:08X} = 0x{value:08X}")

    def irq(self, exc_number, action="pending"):
        """Логировать прерывание."""
        self.debug("IRQ", f"Exception {exc_number}: {action}")

    # ================================================================
    # Summary
    # ================================================================

    def get_summary(self):
        """Получить сводку по количеству сообщений."""
        parts = []
        for lvl in (LogLevel.ERROR, LogLevel.WARN, LogLevel.INFO,
                    LogLevel.DEBUG, LogLevel.TRACE):
            count = self._counts.get(lvl, 0)
            if count > 0:
                parts.append(f"{self._LEVEL_NAMES[lvl]}={count}")
        return "Log: " + ", ".join(parts) if parts else "Log: (empty)"

    def __repr__(self):
        return f"Logger(level={self.level.name})"

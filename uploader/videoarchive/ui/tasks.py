"""Фоновые задачи: долгие операции (сеть, Telegram) не замораживают окно."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)

_alive: set["_Signals"] = set()


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _Signals):
        super().__init__()
        self.fn = fn
        self.signals = signals

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as err:  # noqa: BLE001
            log.debug("Фоновая задача завершилась ошибкой: %s", err)
            self.signals.failed.emit(err)
        else:
            self.signals.done.emit(result)


def run_async(fn: Callable[[], Any], on_done: Callable[[Any], None] | None = None,
              on_error: Callable[[Exception], None] | None = None) -> None:
    """Выполняет fn в пуле потоков; колбэки вызываются в главном потоке."""
    signals = _Signals()
    _alive.add(signals)

    def finish(callback: Callable[[Any], None] | None, value: Any) -> None:
        _alive.discard(signals)
        if callback:
            try:
                callback(value)
            except RuntimeError as err:
                # Окно закрыли, пока шёл запрос: его виджеты уже удалены — это не ошибка.
                if "already deleted" not in str(err):
                    raise
                log.debug("Результат фоновой задачи пришёл в закрытое окно")

    signals.done.connect(lambda r: finish(on_done, r))
    signals.failed.connect(lambda e: finish(on_error, e))
    QThreadPool.globalInstance().start(_Task(fn, signals))

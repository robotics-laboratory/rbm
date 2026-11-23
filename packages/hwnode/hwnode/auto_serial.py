from serial import Serial, SerialException
from threading import Lock
import termios
import time


class AutoReconnectSerial(Serial):
    def __init__(self, *args, logger, reconnect_delay: float = 1.0, **kwargs):
        self.logger = logger
        self.reconnect_delay = reconnect_delay
        self.reconnect_time = -1 * reconnect_delay
        self.reconnect_lock = Lock()
        self.explicitly_closed = True
        super().__init__(**kwargs)

    def _try_open(self):
        if self.is_open: return
        if self.explicitly_closed: return

        with self.reconnect_lock:
            delta = time.perf_counter() - self.reconnect_time
            if delta < self.reconnect_delay: return
            self.reconnect_time = time.perf_counter()
            try:
                super().close()
                super().open()
                self.logger.info(f"Serial connected: {self.port} @ {self.baudrate}")
            except (SerialException, OSError, termios.error) as err:
                self.logger.warn(f"Serial reconnect failed (err: {err})")

    def _safe_call(self, func, args, default):
        try:
            if self.explicitly_closed: return default
            if not self.is_open: self._try_open()
            if self.is_open: return func(*args)
        except (SerialException, OSError, termios.error) as err:
            self.logger.error(f"Serial disconnected (err: {err})")
            super().close()
        return default

    def open(self):
        self.explicitly_closed = False
        self._try_open()

    def close(self):
        try:
            self.explicitly_closed = True
            with self.reconnect_lock:
                super().close()
            self.logger.info("Serial closed explicitly")
        except Exception:
            pass

    def write(self, data):
        return self._safe_call(super().write, [data], 0)

    def flush(self):
        return self._safe_call(super().flush, [], None)

    def read_until(self, data):
        if not self.is_open: time.sleep(self.timeout)
        return self._safe_call(super().read_until, [data], b"")

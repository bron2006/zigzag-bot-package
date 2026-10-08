"""Bound reactor waits without queuing work behind an abandoned OS/DNS call."""
import threading

from twisted.internet.defer import Deferred, fail
from twisted.python.failure import Failure


class BoundedIOTimeout(TimeoutError):
    pass


class BoundedIO:
    def __init__(self, reactor, timeout=10.0):
        self.reactor = reactor
        self.timeout = timeout
        self._slot = threading.Lock()

    def call(self, function, *args, **kwargs):
        if not self._slot.acquire(blocking=False):
            return fail(BoundedIOTimeout("Previous database operation is still running"))
        result = Deferred()

        def expired():
            if not result.called:
                result.errback(BoundedIOTimeout("Database operation exceeded hard deadline"))

        timer = self.reactor.callLater(self.timeout, expired)

        def completed(value, failed):
            if result.called:
                return  # Ignore late results: never resume a timed-out cycle.
            if timer.active():
                timer.cancel()
            (result.errback if failed else result.callback)(value)

        def work():
            try:
                value, failed = function(*args, **kwargs), False
            except BaseException:
                value, failed = Failure(), True
            finally:
                self._slot.release()
            self.reactor.callFromThread(completed, value, failed)

        try:
            threading.Thread(target=work, daemon=True, name="bounded-database-read").start()
        except Exception:
            self._slot.release()
            timer.cancel()
            result.errback(Failure())
        return result

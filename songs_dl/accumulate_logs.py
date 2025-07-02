"""Accumulate logs emitted by a function and return them along with the function's result."""

import contextlib
import logging
import threading
from collections.abc import Callable, Generator
from functools import wraps
from typing import ParamSpec, TypeVar


class AccumulatingLogHandler(logging.Handler):
    """
    A custom log handler that can accumulate and handle all the logs.

    It has a `log_messages` property that contains all the gathered `LogRecord`s
    and a `handle_all` method that displays all the logs.
    """

    def __init__(self) -> None:
        """Initialize the accumulating log handler."""
        super().__init__()
        self.log_messages: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record by appending it to the list of log messages.

        This method is called by the logging framework when a log message is emitted.
        Instead of logging it immediately, we store it in the `log_messages` list
        for later processing.
        """
        # Append the log message to the list
        self.log_messages.append(record)

    def handle_all(self) -> None:
        """Log all accumulated logs with the correct timestamps."""
        for record in self.log_messages:
            # Log the accumulated messages with the current time
            logging.getLogger(record.name).handle(record)  # Log the accumulated messages


P = ParamSpec("P")
R = TypeVar("R")

_lock = getattr(logging, "_lock", threading.RLock())


def lock(lockname: "threading.Lock | threading.RLock") -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Lock a function with a given lock.

    This is useful to ensure that the function is not called concurrently
    when using the accumulating log handler in a concurrent setup.
    """

    def decorator(f: Callable[P, R]) -> Callable[P, R]:
        @wraps(f)
        def wrapper(*args, **kwargs) -> R:
            with lockname:
                return f(*args, **kwargs)

        return wrapper

    return decorator


@contextlib.contextmanager
def patch_logger(logger: logging.Logger, log_handler: logging.Handler) -> Generator[None]:
    """
    Patch a logger: remove all its handlers and add only our one.

    If we are in a concurrent setup, we won't remove and restore the handlers
    but only our log handler.
    """
    # True = we restore the state
    # (and that means we're at the first function call in a concurrent setup)
    # False = we don't restore the state, we just add and remove our log handler
    restore = False

    try:
        with _lock:
            # If there is another log handler, we are the first
            # For some reason, there are NullHandlers in the list
            if any(
                not isinstance(handler, AccumulatingLogHandler | logging.NullHandler) for handler in logger.handlers
            ):
                restore = True

                # Store existing handlers
                existing_handlers = logger.handlers[:]

                # Clear existing handlers
                logger.handlers = []

            # Disable propagation (otherwise the same message would be caught multiple times)
            # Note: old_propagate will be False if we are not the first
            old_propagate = logger.propagate
            logger.propagate = False

            # Add the accumulating handler
            logger.addHandler(log_handler)

        yield

    finally:
        with _lock:
            # Remove our handler
            logger.removeHandler(log_handler)

            # Restore the original handlers only if we are the last
            # (i.e. if there are no other AccumulatingLogHandlers)
            if restore:
                logger.handlers = existing_handlers

            # Restore propagation
            logger.propagate = old_propagate


def accumulate_logs(func: Callable[P, R]) -> Callable[P, tuple[R, AccumulatingLogHandler]]:
    """
    Gathers all the logs emitted by the function. Return a tuple (`result`, `log_handler`).

    See `AccumulatingLogHandler` for more information.
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> tuple[R, AccumulatingLogHandler]:
        # Create an instance of the accumulating log handler
        log_handler = AccumulatingLogHandler()

        # Patch all the loggers
        # (for some reason, the root logger isn't included in loggerDict)
        cms = [
            patch_logger(logger_to_patch, log_handler)
            for logger_to_patch in (logging.root, *logging.root.manager.loggerDict.values())
            if not isinstance(logger_to_patch, logging.PlaceHolder)
        ]

        # Call the original function and unpatch the loggers at the end
        with contextlib.ExitStack() as stack:
            for cm in cms:
                stack.enter_context(cm)
            result = func(*args, **kwargs)

        return (result, log_handler)

    return wrapper

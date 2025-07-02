"""Utilities for running tasks concurrently with callbacks for success, error, and always."""

import concurrent.futures
import sys
from abc import abstractmethod
from collections.abc import Callable
from typing import Protocol, TypeVar

from rich import get_console
from rich.traceback import Traceback

Input = TypeVar("Input")
Output = TypeVar("Output")


class HasStr(Protocol):
    """Protocol for objects that can be converted to a string."""

    @abstractmethod
    def __str__(self) -> str:
        """Return a string representation of the object."""


def run_tasks(  # noqa: PLR0913, PLR0917
    actions: list[Input],
    callback: Callable[[Input], Output],
    success_callback: Callable[[Input, Output], None] | None = None,
    error_callback: Callable[[Input, Exception], None] | None = None,
    always_callback: Callable[[Input], None] | None = None,
    max_workers: int | None = None,
) -> list[Output]:
    """Run a list of actions concurrently with callbacks for success, error, and always."""
    if not error_callback:

        def error_callback(action: HasStr, error: Exception) -> None:
            print(f"Error when executing {action}:", file=sys.stderr)
            get_console().print(Traceback.from_exception(type(error), error, error.__traceback__))

    ret = []

    with concurrent.futures.ThreadPoolExecutor(max_workers) as executor:
        future_to_action = {executor.submit(callback, action): action for action in actions}
        for future in concurrent.futures.as_completed(future_to_action):
            action = future_to_action[future]
            try:
                result = future.result()
            except Exception:  # noqa: BLE001
                if error_callback:
                    error_callback(action, sys.exc_info()[1])
            else:
                ret.append(result)
                if success_callback:
                    success_callback(action, result)
            finally:
                if always_callback:
                    always_callback(action)

    return ret

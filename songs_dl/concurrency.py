import concurrent.futures
import sys
from typing import Callable, TypeVar

from rich import get_console
from rich.traceback import Traceback

I = TypeVar("I")
O = TypeVar("O")


def run_tasks(
    actions: list[I],
    callback: Callable[[I], O],
    success_callback: Callable[[I, O], None] | None = None,
    error_callback: Callable[[I, Exception], None] | None = None,
    always_callback: Callable[[I], None] | None = None,
    max_workers: int | None = None,
) -> list[O]:
    if not error_callback:

        def error_callback(action, error):
            print(f"Error when executing {action}:", file=sys.stderr)
            get_console().print(Traceback.from_exception(type(error), error, error.__traceback__))

    ret = []

    with concurrent.futures.ThreadPoolExecutor(max_workers) as executor:
        future_to_action = {executor.submit(callback, action): action for action in actions}
        for future in concurrent.futures.as_completed(future_to_action):
            action = future_to_action[future]
            try:
                result = future.result()
            except Exception:
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

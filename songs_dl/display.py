from itertools import chain
from typing import Callable, Generic, ParamSpec, TypeVar

from rich.progress import Progress

from .accumulate_logs import AccumulatingLogHandler, accumulate_logs
from .concurrency import run_tasks

P = ParamSpec("P")
R = TypeVar("R")


class Action(Generic[R]):
    """Represents an action to be performed, such as downloading a song or adding tags."""

    def __init__(
        self,
        description: str,
        callback: Callable[P, R] | None = None,
        progress: Progress | None = None,
        expanded=False,
        no_task=False,
    ):
        self._results: R | None = None
        self._completed = 0
        self._total = 0
        self.expanded = expanded
        self.no_task = no_task
        self.logs: AccumulatingLogHandler | None = None
        self.error: Exception | None = None
        self.parent: "ActionsGroup[R] | None" = None

        self._description = description
        self.callback = callback
        self._task = None
        self._progress = None
        self.progress = progress
        self.task  # Create the task

    def __call__(self, *args, **kwargs):
        try:
            self.results, self.logs = accumulate_logs(self.callback)(*args, **kwargs)
        except Exception as e:
            self.error = e
        finally:
            self.total = self.total or 1
            self.completed = self.total

    @property
    def progress(self) -> Progress | None:
        """Return the progress instance associated with this action."""
        if self.parent:
            if self.expanded:
                return self.parent.progress
            if self._progress:
                raise ValueError("A progress bar can't be set if the action has a parent")
        return self._progress

    @progress.setter
    def progress(self, value: Progress | None):
        """Set the progress instance for this action."""
        if self.parent and not self.expanded:
            raise ValueError(
                "A progress bar can't be set if the action has a parent. "
                "If you really want to, set self.expanded to True."
            )
        self._progress = value
        self.task

    @property
    def task(self):
        """Create a task in the progress bar."""
        if not self.no_task and self.progress and self._task is None:
            self._task = self.progress.add_task(self.description, total=None)
        return self._task

    @property
    def results(self) -> R | None:
        """Return the results of the action."""
        return self._results

    @results.setter
    def results(self, value: R | None):
        """Set the results of the action."""
        self._results = value
        self.description = self._description

    @property
    def description(self):
        """Description of the action."""
        return (
            self._description
            + (" :cross_mark:" if self.error else "")
            + (f" ({len(self.results)})" if self.results is not None else "")
        )

    @description.setter
    def description(self, value: str):
        """Set the description of the action."""
        self._description = value
        self.update()

    def _get_completed(self):
        return self._completed

    @property
    def completed(self) -> float:
        """Return the number of completed tasks for this action."""
        return self._get_completed()

    @completed.setter
    def completed(self, value: float):
        self._completed = value
        self.update()

    def _get_total(self):
        return self._total

    @property
    def total(self) -> float | None:
        """Return the total number of tasks for this action."""
        return self._get_total() or None

    @total.setter
    def total(self, value: float):
        self._total = value
        self.update()

    def update(self):
        if self.task:
            self.progress.update(
                self.task,
                description=self.description,
                completed=self.completed,
                total=self.total,
            )
        if self.parent:
            self.parent.update()


class ActionsGroup(Action, Generic[R]):
    """A group of actions to be executed together."""

    def __init__(
        self,
        description: str,
        actions: list[Action[R]] | None = None,
        ponderations: dict[Action[R], float] | Callable[[str], float] | None = None,
        expandable=False,
        calibrate=False,
        max_workers: float | None = None,
        *args, **kwargs,
    ):
        self.actions = []
        self.ponderations = ponderations or {}
        self.calibrate = calibrate
        self.expandable = expandable
        self.max_workers = max_workers

        super().__init__(description, *args, **kwargs)

        for action in (actions or []):
            self.add_action(action)

    def add_action(self, action: "Action"[R]):
        """Add an action to the parent group."""
        self.actions.append(action)
        action.parent = self
        action.expanded = self.expandable
        action.task  # Create the task
        self.update()

    def __call__(self, *args, **kwargs):
        try:
            return run_tasks(
                [action for action in self if action.callback],
                lambda action: action(*args, **kwargs),
                max_workers=self.max_workers,
            )
        except Exception as e:
            self.error = e

    def __iter__(self):
        """Iterate over the actions in the group."""
        return iter(self.actions)

    @property
    def results(self) -> list[R]:
        """Return the results of all actions in the group."""
        return list(chain.from_iterable(action.results or [] for action in self))

    def get_ponderation(self, action: Action[R]) -> float:
        """Get the ponderation for a specific action."""
        if callable(self.ponderations):
            return self.ponderations(action)
        return self.ponderations.get(action, 1)

    def _get_completed(self) -> float:
        """Return the number of completed tasks for this action group."""
        return sum(
            action.completed / ((action.total or 1) if self.calibrate else 1) * self.get_ponderation(action)
            for action in self
        )

    def _get_total(self) -> float:
        """Return the total number of tasks for this action group."""
        return sum(
            (1 if self.calibrate else (action.total or 1)) * self.get_ponderation(action)
            for action in self
        )

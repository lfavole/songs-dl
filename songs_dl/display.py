"""Actions and ActionsGroup classes for managing tasks with progress tracking."""

from collections.abc import Callable, Iterator
from itertools import chain
from typing import Generic, ParamSpec, TypeVar

from rich.progress import Progress, TaskID

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
        expanded: bool = False,
        no_task: bool = False,
    ) -> None:
        """Initialize an Action instance."""
        self._results: R | None = None
        self._completed = 0
        self._total = 0
        self.expanded = expanded
        self.no_task = no_task
        self.logs: AccumulatingLogHandler | None = None
        self.error: Exception | None = None
        self.parent: ActionsGroup[R] | None = None

        self._description = description
        self.callback = callback
        self._task = None
        self._progress = None
        self.progress = progress
        _ = self.task  # Create the task

    def __call__(self, *args, **kwargs) -> None:
        """Execute the action and accumulate logs."""
        try:
            self.results, self.logs = accumulate_logs(self.callback)(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            self.error = e
        finally:
            self.total = self.total or 1
            self.completed = self.total

    @property
    def progress(self) -> Progress | None:
        """
        Return the progress instance associated with this action.

        Raises:
            ValueError: If the action has a parent and is not expanded, or if the progress is already set.

        """
        if self.parent:
            if self.expanded:
                return self.parent.progress
            if self._progress:
                msg = "A progress bar can't be set if the action has a parent"
                raise ValueError(msg)
        return self._progress

    @progress.setter
    def progress(self, value: Progress | None) -> None:
        """
        Set the progress instance for this action.

        Raises:
            ValueError: If the action has a parent and is not expanded, or if the progress is already set.

        """
        if self.parent and not self.expanded:
            msg = (
                "A progress bar can't be set if the action has a parent. "
                "If you really want to, set self.expanded to True."
            )
            raise ValueError(msg)
        self._progress = value
        _ = self.task  # Create the task if not already created

    @property
    def task(self) -> TaskID:
        """Create a task in the progress bar."""
        if not self.no_task and self.progress and self._task is None:
            self._task = self.progress.add_task(self.description, total=None)
        return self._task

    @property
    def results(self) -> R | None:
        """Return the results of the action."""
        return self._results

    @results.setter
    def results(self, value: R | None) -> None:
        """Set the results of the action."""
        self._results = value
        self.description = self._description

    @property
    def description(self) -> str:
        """Description of the action."""
        return (
            self._description
            + (" :cross_mark:" if self.error else "")
            + (f" ({len(self.results)})" if self.results is not None else "")
        )

    @description.setter
    def description(self, value: str) -> None:
        """Set the description of the action."""
        self._description = value
        self.update()

    def _get_completed(self) -> float:
        """
        Return the number of completed tasks for this action.

        This method should be overridden in subclasses instead of the completed property.
        """
        return self._completed

    @property
    def completed(self) -> float:
        """Return the number of completed tasks for this action."""
        return self._get_completed()

    @completed.setter
    def completed(self, value: float) -> None:
        """Set the number of completed tasks for this action."""
        self._completed = value
        self.update()

    def _get_total(self) -> float | None:
        """
        Return the total number of tasks for this action or None if the progress is indeterminate.

        This method should be overridden in subclasses instead of the total property.
        """
        return self._total

    @property
    def total(self) -> float | None:
        """Return the total number of tasks for this action."""
        return self._get_total() or None

    @total.setter
    def total(self, value: float) -> None:
        """Set the total number of tasks for this action."""
        self._total = value
        self.update()

    def update(self) -> None:
        """Update the progress bar with the current state of the action."""
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

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        description: str,
        actions: list[Action[R]] | None = None,
        ponderations: dict[Action[R], float] | Callable[[str], float] | None = None,
        expandable: bool = False,
        calibrate: bool = False,
        max_workers: float | None = None,
        *args,
        **kwargs,
    ) -> None:
        """Initialize an ActionsGroup instance."""
        self.actions = []
        self.ponderations = ponderations or {}
        self.calibrate = calibrate
        self.expandable = expandable
        self.max_workers = max_workers

        super().__init__(description, *args, **kwargs)

        for action in actions or []:
            self.add_action(action)

    def add_action(self, action: "Action[R]") -> None:
        """Add an action to the parent group."""
        self.actions.append(action)
        action.parent = self
        action.expanded = self.expandable
        _ = action.task  # Create the task
        self.update()

    def __call__(self, *args, **kwargs) -> list[R] | None:
        """Execute all actions in the group concurrently."""
        try:
            return run_tasks(
                [action for action in self if action.callback],
                lambda action: action(*args, **kwargs),
                max_workers=self.max_workers,
            )
        except Exception as e:  # noqa: BLE001
            self.error = e

    def __iter__(self) -> Iterator[Action[R]]:
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
        return sum((1 if self.calibrate else (action.total or 1)) * self.get_ponderation(action) for action in self)

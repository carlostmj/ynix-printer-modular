from __future__ import annotations


class EditHistory:
    def __init__(self, limit: int = 100) -> None:
        self.limit = limit
        self.undo_stack: list[dict[str, object]] = []
        self.redo_stack: list[dict[str, object]] = []
        self.last_snapshot: dict[str, object] | None = None
        self.batch_start: dict[str, object] | None = None

    @property
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def reset(self, snapshot: dict[str, object]) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.last_snapshot = dict(snapshot)
        self.batch_start = None

    def record(self, snapshot: dict[str, object]) -> None:
        snapshot = dict(snapshot)
        if self.last_snapshot is None:
            self.last_snapshot = snapshot
            return
        if snapshot == self.last_snapshot:
            return
        self.undo_stack.append(dict(self.last_snapshot))
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.last_snapshot = snapshot

    def begin_batch(self, snapshot: dict[str, object]) -> None:
        self.batch_start = dict(snapshot)

    def commit_batch(self, snapshot: dict[str, object]) -> bool:
        snapshot = dict(snapshot)
        if self.batch_start is None:
            self.last_snapshot = snapshot
            return False
        start = self.batch_start
        self.batch_start = None
        if start == snapshot:
            self.last_snapshot = snapshot
            return False
        self.undo_stack.append(start)
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.last_snapshot = snapshot
        return True

    def undo(self, current: dict[str, object]) -> dict[str, object] | None:
        if not self.undo_stack:
            return None
        previous = self.undo_stack.pop()
        self.redo_stack.append(dict(current))
        self.last_snapshot = dict(previous)
        return previous

    def redo(self, current: dict[str, object]) -> dict[str, object] | None:
        if not self.redo_stack:
            return None
        next_snapshot = self.redo_stack.pop()
        self.undo_stack.append(dict(current))
        self.last_snapshot = dict(next_snapshot)
        return next_snapshot

"""Structured task plans used to gate the VERIFY → DONE transition."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True)
class PlanItem:
    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "content": self.content, "status": self.status.value}

    @classmethod
    def from_value(cls, value: PlanItem | Mapping[str, Any]) -> PlanItem:
        if isinstance(value, cls):
            value = {
                "id": value.id,
                "content": value.content,
                "status": value.status.value if isinstance(value.status, TodoStatus) else value.status,
            }
        if not isinstance(value, Mapping):
            raise ValueError("each plan item must be an object")  # noqa: TRY004
        item_id = value.get("id")
        content = value.get("content", value.get("title"))
        status = value.get("status", TodoStatus.PENDING.value)
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError("plan item id must be a non-empty string")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("plan item content must be a non-empty string")
        if not isinstance(status, str):
            raise ValueError(  # noqa: TRY004
                "plan item status must be pending, in_progress, or completed"
            )
        try:
            parsed_status = TodoStatus(status)
        except ValueError as exc:
            raise ValueError(
                "plan item status must be pending, in_progress, or completed"
            ) from exc
        return cls(item_id, content, parsed_status)


class PlanTodoList:
    """Validated ordered list of plan items.

    ``replace`` is atomic: an invalid update leaves the current plan
    untouched. Empty plans are allowed while a task is being gathered, but
    cannot satisfy the completion gate.
    """

    def __init__(self, items: Iterable[PlanItem | Mapping[str, Any]] = ()) -> None:
        self._items: list[PlanItem] = []
        initial = list(items)
        if initial:
            self.replace(initial)

    @property
    def items(self) -> tuple[PlanItem, ...]:
        return tuple(self._items)

    @property
    def all_completed(self) -> bool:
        return bool(self._items) and all(
            item.status is TodoStatus.COMPLETED for item in self._items
        )

    @property
    def is_complete(self) -> bool:
        return self.all_completed

    def replace(self, items: Iterable[PlanItem | Mapping[str, Any]]) -> tuple[PlanItem, ...]:
        candidate = [PlanItem.from_value(item) for item in items]
        ids = [item.id for item in candidate]
        if len(ids) != len(set(ids)):
            raise ValueError("plan item ids must be unique")
        in_progress = sum(item.status is TodoStatus.IN_PROGRESS for item in candidate)
        if in_progress > 1:
            raise ValueError("plan may contain at most one in_progress item")
        self._items = candidate
        return self.items

    def update(
        self, items: Iterable[PlanItem | Mapping[str, Any]], *, replace: bool = False
    ) -> tuple[PlanItem, ...]:
        """Apply partial item updates while preserving the ordered plan."""

        if replace:
            return self.replace(items)
        current = {item.id: item for item in self._items}
        order = [item.id for item in self._items]
        seen_ids: set[str] = set()
        for raw_item in items:
            if isinstance(raw_item, PlanItem):
                item_id = raw_item.id
            elif isinstance(raw_item, Mapping):
                item_id = raw_item.get("id")
            else:
                raise ValueError("each plan update must be an object")  # noqa: TRY004
            if not isinstance(item_id, str) or not item_id.strip():
                raise ValueError("plan update id must be a non-empty string")
            if item_id in seen_ids:
                raise ValueError("plan update ids must be unique")
            seen_ids.add(item_id)
            if isinstance(raw_item, PlanItem):
                item = PlanItem.from_value(raw_item)
                current[item.id] = item
                if item.id not in order:
                    order.append(item.id)
                continue
            previous = current.get(item_id)
            if previous is None:
                current[item_id] = PlanItem.from_value(raw_item)
                order.append(item_id)
                continue
            content = raw_item.get("content", raw_item.get("title", previous.content))
            status = raw_item.get("status", previous.status.value)
            current[item_id] = PlanItem.from_value(
                {"id": item_id, "content": content, "status": status}
            )
        return self.replace([current[item_id] for item_id in order])

    def to_list(self) -> list[dict[str, str]]:
        return [item.to_dict() for item in self._items]

    def from_list(self, items: Iterable[PlanItem | Mapping[str, Any]]) -> tuple[PlanItem, ...]:
        return self.replace(items)

    @classmethod
    def from_value(cls, value: Iterable[PlanItem | Mapping[str, Any]]) -> PlanTodoList:
        return cls(value)


PlanTodo = PlanItem
Plan = PlanTodoList
PlanStatus = TodoStatus

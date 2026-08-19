"""Port: رویدادها — جایگزین EventBus."""

from typing import Any, Callable, Protocol


class IEventPublisher(Protocol):
    def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...
    def subscribe(self, event_type: str, handler: Callable[..., None]) -> None: ...

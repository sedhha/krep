from collections.abc import Mapping
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel

ConfigModel = type[BaseModel]


class AuthAdapter(Protocol):
    type: ClassVar[str]
    config_model: ClassVar[ConfigModel]
    secret_fields: ClassVar[tuple[str, ...]]

    def verify(
        self, token: str, config: BaseModel, secrets: Mapping[str, str]
    ) -> Mapping[str, Any]: ...


_registry: dict[str, AuthAdapter] = {}


def register(adapter: AuthAdapter) -> None:
    _registry[adapter.type] = adapter


def unregister(adapter_type: str) -> None:
    _registry.pop(adapter_type, None)


def get_adapter(adapter_type: str) -> AuthAdapter:
    return _registry[adapter_type]


def list_adapters() -> list[dict[str, Any]]:
    return [
        {
            "type": adapter.type,
            "config_schema": adapter.config_model.model_json_schema(),
            "secret_fields": list(adapter.secret_fields),
        }
        for adapter in _registry.values()
    ]

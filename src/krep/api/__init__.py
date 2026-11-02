from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from krep.api.main import app as app
    from krep.api.main import create_app as create_app

__all__ = ["app", "create_app"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        return getattr(import_module("krep.api.main"), name)
    raise AttributeError(name)

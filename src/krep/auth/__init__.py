from krep.auth.adapters import AuthAdapter, get_adapter, list_adapters, register
from krep.auth.hmac import HmacAdapter

register(HmacAdapter())

__all__ = ["AuthAdapter", "get_adapter", "list_adapters", "register"]

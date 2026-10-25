from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.dialects.postgresql import base as pg_base
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeEngine, UserDefinedType


class JsonPath(UserDefinedType[str]):
    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "jsonpath"


ischema_names: dict[str, type[TypeEngine[Any]]] = vars(pg_base)["ischema_names"]
ischema_names["jsonpath"] = JsonPath


class Base(DeclarativeBase):
    metadata = MetaData()

from typing import Annotated

from pydantic import Field, StringConstraints

Group = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Groups = Annotated[list[Group], Field(max_length=20)]

from collections.abc import Mapping
from typing import Any, ClassVar, Literal

import jwt
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from krep.api.errors import ApiError

ConfigModel = type[BaseModel]
MIN_SECRET_BYTES = 32
LEEWAY_SECONDS = 30


class HmacConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: SecretStr
    algorithms: list[Literal["HS256", "HS384", "HS512"]] = Field(
        default_factory=lambda: ["HS256"], min_length=1
    )
    audience: str | None = None
    issuer: str | None = None
    user_claim_path: list[str] = Field(default_factory=lambda: ["sub"], min_length=1)
    allow_principal: bool = False

    @field_validator("secret")
    @classmethod
    def _long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode()) < MIN_SECRET_BYTES:
            raise ValueError(f"secret must be at least {MIN_SECRET_BYTES} bytes")
        return value


class HmacAdapter:
    type: ClassVar[str] = "hmac"
    config_model: ClassVar[ConfigModel] = HmacConfig
    secret_fields: ClassVar[tuple[str, ...]] = ("secret",)

    def verify(
        self, token: str, config: BaseModel, secrets: Mapping[str, str]
    ) -> Mapping[str, Any]:
        assert isinstance(config, HmacConfig)
        try:
            return jwt.decode(
                token,
                secrets["secret"],
                algorithms=list(config.algorithms),
                audience=config.audience,
                issuer=config.issuer,
                leeway=LEEWAY_SECONDS,
                options={
                    "require": ["exp"],
                    "verify_aud": config.audience is not None,
                },
            )
        except jwt.PyJWTError:
            raise ApiError(
                401, "unauthenticated", "invalid or missing credentials"
            ) from None

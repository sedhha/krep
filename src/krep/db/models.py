import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column

from krep.db.base import Base, JsonPath


def uuid_pk() -> MappedColumn[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def timestamp() -> MappedColumn[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class RegistryType(Base):
    __tablename__ = "registry_types"
    __table_args__ = (CheckConstraint("type ~ '^[a-z][a-z0-9_]{1,31}$'"),)

    type: Mapped[str] = mapped_column(Text, primary_key=True)
    subtype_table: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")


class AccessPolicy(Base):
    __tablename__ = "access_policies"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 120"),
        CheckConstraint("char_length(description) <= 1000"),
        UniqueConstraint("tenant_id", "name"),
        UniqueConstraint("id", "tenant_id"),
        Index("access_policies_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    ast: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(Text)
    compiled_path: Mapped[str] = mapped_column(JsonPath())
    compiler_version: Mapped[int] = mapped_column(SmallInteger)
    reserved: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    rev: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp()
    updated_by: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = timestamp()


class AccessPolicyHistory(Base):
    __tablename__ = "access_policy_history"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("access_policies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rev: Mapped[int] = mapped_column(Integer, primary_key=True)
    ast: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = timestamp()


class Registry(Base):
    __tablename__ = "registry"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120"),
        CheckConstraint("char_length(description) <= 2000"),
        CheckConstraint("cardinality(tags) <= 20"),
        CheckConstraint("visibility IN ('private','tenant','restricted')"),
        CheckConstraint("status IN ('draft','published','archived')"),
        CheckConstraint("pg_column_size(meta) <= 16384"),
        CheckConstraint("visibility <> 'restricted' OR policy_id IS NOT NULL"),
        UniqueConstraint("tenant_id", "type", "slug"),
        UniqueConstraint("id", "type"),
        UniqueConstraint("id", "tenant_id"),
        ForeignKeyConstraint(
            ["policy_id", "tenant_id"],
            ["access_policies.id", "access_policies.tenant_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["current_version_id"],
            ["registry_versions.id"],
            name="registry_current_version_id_fkey",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("registry_tenant_type_status", "tenant_id", "type", "status"),
        Index("registry_tags_gin", "tags", postgresql_using="gin"),
        Index("registry_tsv_gin", "search_tsv", postgresql_using="gin"),
        Index(
            "registry_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(Text, ForeignKey("registry_types.type"))
    slug: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    visibility: Mapped[str] = mapped_column(Text, server_default="private")
    policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    next_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(name,'')), 'A') || "
            "setweight(to_tsvector('english', coalesce(description,'')), 'B') || "
            "setweight(to_tsvector('english', immutable_array_to_string(tags,' ')), 'C')",
            persisted=True,
        ),
        nullable=True,
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    created_at: Mapped[datetime] = timestamp()
    created_by: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = timestamp()
    updated_by: Mapped[str] = mapped_column(Text)


class RegistryVersion(Base):
    __tablename__ = "registry_versions"
    __table_args__ = (
        CheckConstraint("status IN ('draft','published')"),
        CheckConstraint(
            "(status = 'published') = (published_at IS NOT NULL AND content_hash IS NOT NULL)"
        ),
        UniqueConstraint("registry_id", "version"),
        UniqueConstraint("id", "registry_id"),
        Index(
            "registry_versions_drafts",
            "tenant_id",
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    registry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("registry.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    content_hash: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("type = 'agent'"),
        ForeignKeyConstraint(
            ["version_id", "registry_id"],
            ["registry_versions.id", "registry_versions.registry_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["registry_id", "type"],
            ["registry.id", "registry.type"],
            ondelete="CASCADE",
        ),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    registry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(Text, server_default="agent")
    model: Mapped[str] = mapped_column(Text)
    model_config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    system_prompt: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    hitl_rules: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    runtime_config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    tool_refs: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))


class SkillFile(Base):
    __tablename__ = "skill_files"
    __table_args__ = (
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'"),
        CheckConstraint("size_bytes BETWEEN 1 AND 1048576"),
        CheckConstraint("size_bytes = octet_length(content)"),
        CheckConstraint("sha256(content) = decode(content_sha256, 'hex')"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    content_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary)


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        CheckConstraint("type = 'skill'"),
        ForeignKeyConstraint(
            ["version_id", "registry_id"],
            ["registry_versions.id", "registry_versions.registry_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["registry_id", "type"],
            ["registry.id", "registry.type"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "content_sha256"],
            ["skill_files.tenant_id", "skill_files.content_sha256"],
            ondelete="RESTRICT",
        ),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    registry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(Text, server_default="skill")
    content_sha256: Mapped[str] = mapped_column(Text)


class LinkRule(Base):
    __tablename__ = "link_rules"
    __table_args__ = (CheckConstraint("accept_by IN ('source','target')"),)

    source_type: Mapped[str] = mapped_column(
        Text, ForeignKey("registry_types.type"), primary_key=True
    )
    target_type: Mapped[str] = mapped_column(
        Text, ForeignKey("registry_types.type"), primary_key=True
    )
    relation: Mapped[str] = mapped_column(Text, primary_key=True)
    auto_load_allowed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    accept_by: Mapped[str] = mapped_column(Text)


class RegistryLink(Base):
    __tablename__ = "registry_links"
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','rejected')"),
        CheckConstraint("source_id <> target_id"),
        CheckConstraint("origin_id IN (source_id, target_id)"),
        UniqueConstraint("tenant_id", "source_id", "target_id", "relation"),
        Index("registry_links_src", "tenant_id", "source_id", "relation"),
        Index("registry_links_tgt", "tenant_id", "target_id", "relation"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("registry.id", ondelete="CASCADE")
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("registry.id", ondelete="RESTRICT")
    )
    relation: Mapped[str] = mapped_column(Text)
    pinned_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("registry_versions.id", ondelete="RESTRICT")
    )
    auto_load: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    origin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp()


class RegistryVersionDep(Base):
    __tablename__ = "registry_version_deps"
    __table_args__ = (Index("registry_version_deps_rev", "depends_on_version_id"),)

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registry_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    depends_on_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registry_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    relation: Mapped[str] = mapped_column(Text, primary_key=True)
    auto_load: Mapped[bool] = mapped_column(Boolean)


class ResourceLimit(Base):
    __tablename__ = "resource_limits"
    __table_args__ = (
        CheckConstraint("scope_type IN ('global','tenant','org','product')"),
        CheckConstraint("value >= 0"),
        CheckConstraint("(scope_type = 'global') = (scope_id IS NULL)"),
        UniqueConstraint(
            "scope_type",
            "scope_id",
            "resource_type",
            "limit_key",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scope_type: Mapped[str] = mapped_column(Text)
    scope_id: Mapped[str | None] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(Text, ForeignKey("registry_types.type"))
    limit_key: Mapped[str] = mapped_column(Text)
    value: Mapped[int] = mapped_column(Integer)


class SearchSynonym(Base):
    __tablename__ = "search_synonyms"
    __table_args__ = (
        CheckConstraint("cardinality(terms) BETWEEN 2 AND 10"),
        Index("search_synonyms_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    terms: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp()


class TokenIssuer(Base):
    __tablename__ = "token_issuers"
    __table_args__ = (
        CheckConstraint("left(jwks_uri, 8) = 'https://'"),
        CheckConstraint("(tenant_id IS NOT NULL) <> (tenant_claim_path IS NOT NULL)"),
    )

    issuer: Mapped[str] = mapped_column(Text, primary_key=True)
    audience: Mapped[str] = mapped_column(Text)
    jwks_uri: Mapped[str] = mapped_column(Text)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tenant_claim_path: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    user_claim_path: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{sub}'"))
    allow_principal: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    allow_principal: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = timestamp()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

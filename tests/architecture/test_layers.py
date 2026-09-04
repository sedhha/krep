"""Enforcement of the layer graph documented in docs/architecture/overview.md.

This module is authoritative: the diagram in the architecture overview is its
readable summary. Widening ALLOWED_IMPORTS is a Level 3 change under
docs/WORKFLOW.md and requires an ADR.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "krep"
PACKAGE_NAME = "krep"

LEAF: frozenset[str] = frozenset()
ADAPTERS = frozenset({"shared"})
CROSS_CUTTING = frozenset({"shared", "integrations"})
CAPABILITY_BASE = CROSS_CUTTING | {"telemetry"}

ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "shared": LEAF,
    "integrations": ADAPTERS,
    "telemetry": CROSS_CUTTING,
    "connections": CAPABILITY_BASE,
    "authorization": CAPABILITY_BASE,
    "runs": CAPABILITY_BASE,
    "hitl": CAPABILITY_BASE,
    "tools": CAPABILITY_BASE | {"connections", "authorization"},
    "agents": CAPABILITY_BASE | {"tools"},
    "runtime": CAPABILITY_BASE
    | {"agents", "tools", "runs", "hitl", "authorization", "connections"},
    "evaluation": CAPABILITY_BASE | {"agents", "runs", "runtime"},
    "api": CAPABILITY_BASE
    | {"agents", "tools", "runs", "hitl", "authorization", "connections", "runtime", "evaluation"},
    "workers": CAPABILITY_BASE
    | {"agents", "tools", "runs", "hitl", "authorization", "connections", "runtime", "evaluation"},
}

ENTRYPOINTS = frozenset({"api", "workers"})


def _top_level_packages() -> list[str]:
    return sorted(
        path.name
        for path in PACKAGE_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith(".") and (path / "__init__.py").exists()
    )


def _modules() -> Iterator[tuple[str, Path]]:
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative = path.relative_to(PACKAGE_ROOT)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if len(relative.parts) == 1:
            continue
        yield relative.parts[0], path


def _imported_packages(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    owner = path.relative_to(PACKAGE_ROOT).parts[0]
    imported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                depth = len(path.relative_to(PACKAGE_ROOT).parts) - 1
                names = [owner] if node.level <= depth else []
            else:
                names = [node.module or ""]
        else:
            continue

        for name in names:
            parts = name.split(".")
            if parts[0] == PACKAGE_NAME and len(parts) > 1:
                imported.add(parts[1])
            elif parts[0] == owner and name != owner:
                imported.add(owner)

    return imported - {owner}


def test_every_package_declares_its_allowed_imports() -> None:
    declared = set(ALLOWED_IMPORTS)
    actual = set(_top_level_packages())
    assert actual - declared == set(), (
        f"packages missing from ALLOWED_IMPORTS: {sorted(actual - declared)}. "
        "A new top-level package is an architectural change: document it in "
        "docs/architecture/overview.md and declare its legal dependencies here."
    )
    assert declared - actual == set(), (
        f"ALLOWED_IMPORTS names packages that do not exist: {sorted(declared - actual)}"
    )


def test_allowed_imports_reference_real_packages() -> None:
    for package, allowed in ALLOWED_IMPORTS.items():
        unknown = allowed - set(ALLOWED_IMPORTS)
        assert not unknown, f"{package} is allowed to import unknown packages: {sorted(unknown)}"


def test_no_package_may_import_an_entrypoint() -> None:
    offenders = {
        package: sorted(allowed & ENTRYPOINTS)
        for package, allowed in ALLOWED_IMPORTS.items()
        if allowed & ENTRYPOINTS
    }
    assert not offenders, (
        f"transports must be leaves in the reverse direction; offenders: {offenders}"
    )


def test_layer_graph_is_acyclic() -> None:
    visiting: set[str] = set()
    settled: set[str] = set()

    def walk(package: str, trail: tuple[str, ...]) -> None:
        if package in settled:
            return
        assert package not in visiting, f"import cycle: {' -> '.join((*trail, package))}"
        visiting.add(package)
        for dependency in sorted(ALLOWED_IMPORTS.get(package, LEAF)):
            walk(dependency, (*trail, package))
        visiting.discard(package)
        settled.add(package)

    for package in ALLOWED_IMPORTS:
        walk(package, ())


@pytest.mark.parametrize("package", _top_level_packages())
def test_package_imports_respect_the_layer_graph(package: str) -> None:
    allowed = ALLOWED_IMPORTS[package]
    violations: list[str] = []

    for owner, path in _modules():
        if owner != package:
            continue
        for imported in sorted(_imported_packages(path)):
            if imported not in allowed:
                location = path.relative_to(PACKAGE_ROOT)
                violations.append(f"{location} imports krep.{imported}")

    assert not violations, (
        f"'{package}' may import {sorted(allowed) or 'nothing internal'}; violations:\n  "
        + "\n  ".join(violations)
        + "\nSee docs/architecture/overview.md. Widening the graph requires an ADR."
    )

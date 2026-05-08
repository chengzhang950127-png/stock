"""Generate ``docs/CONTRACTS.md`` from Pydantic models in :mod:`src.contracts`.

Run via ``make contracts`` (writes to stdout, redirected by the Makefile).
"""

from __future__ import annotations

import inspect
from typing import get_type_hints

from pydantic import BaseModel

from src import contracts


def _format_field(field_name: str, hint: str, default: str | None) -> str:
    base = f"- `{field_name}`: `{hint}`"
    if default is not None:
        base += f" (default: `{default}`)"
    return base


def render() -> str:
    out: list[str] = []
    out.append("# Contracts (auto-generated)")
    out.append("")
    out.append(
        "Source of truth: `src/contracts.py`. Run `make contracts` after changing "
        "the Pydantic models to refresh this document."
    )
    out.append("")

    # Enums first
    out.append("## Enums")
    out.append("")
    for name in dir(contracts):
        obj = getattr(contracts, name)
        if (
            inspect.isclass(obj)
            and issubclass(obj, str)
            and hasattr(obj, "__members__")
            and obj.__module__ == contracts.__name__
        ):
            out.append(f"### `{name}`")
            out.append("")
            for member in obj:
                out.append(f"- `{member.name}` = `{member.value!r}`")
            out.append("")

    # Models
    out.append("## Models")
    out.append("")
    for name in dir(contracts):
        obj = getattr(contracts, name)
        if (
            inspect.isclass(obj)
            and issubclass(obj, BaseModel)
            and obj is not BaseModel
            and obj.__module__ == contracts.__name__
        ):
            out.append(f"### `{name}`")
            out.append("")
            # Only show the docstring if defined on the class itself
            # (not the inherited BaseModel docstring).
            if obj.__doc__ and obj.__doc__ is not BaseModel.__doc__:
                out.append(inspect.cleandoc(obj.__doc__))
                out.append("")
            try:
                hints = get_type_hints(obj)
            except Exception:
                hints = {}
            for field_name, field in obj.model_fields.items():
                hint = hints.get(field_name, field.annotation)
                hint_repr = getattr(hint, "__name__", str(hint))
                default: str | None = None
                # Pydantic's PydanticUndefined sentinel means "no default" — skip.
                from pydantic_core import PydanticUndefined

                if field.default is not None and field.default is not PydanticUndefined:
                    default = repr(field.default)
                elif field.default_factory is not None:
                    default = f"<factory: {field.default_factory.__name__}>"
                out.append(_format_field(field_name, hint_repr, default))
            out.append("")

    return "\n".join(out)


if __name__ == "__main__":
    print(render())

"""
File-based JSON cache for data-fetch functions.

The cache lives under ``.cache/yfinance/`` (gitignored). Each key hashes to
a single JSON file containing the cached value plus the time it was written.
Reads check the TTL before returning. Misses fall through to the wrapped
function and write the result back.

Both sync and async callables are supported via a single ``@cached``
decorator. Cached values must be JSON-serialisable through the supplied
serialiser/deserialiser pair (default: :func:`json.dumps`/:func:`json.loads`,
augmented to handle ``Decimal``, ``date``, ``datetime``, and Pydantic models).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import BaseModel

DEFAULT_CACHE_DIR = Path(".cache/yfinance")

T = TypeVar("T")


class _CacheEncoder(json.JSONEncoder):
    """JSON encoder that knows about Decimal/date/datetime/Pydantic."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return {"__decimal__": str(o)}
        if isinstance(o, datetime):
            return {"__datetime__": o.isoformat()}
        if isinstance(o, date):
            return {"__date__": o.isoformat()}
        if isinstance(o, BaseModel):
            return {"__model__": type(o).__name__, "data": o.model_dump(mode="json")}
        return super().default(o)


def _decode(obj: Any) -> Any:
    if isinstance(obj, dict):
        if "__decimal__" in obj:
            return Decimal(obj["__decimal__"])
        if "__datetime__" in obj:
            return datetime.fromisoformat(obj["__datetime__"])
        if "__date__" in obj:
            return date.fromisoformat(obj["__date__"])
        return {k: _decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    return obj


def _stable_repr(value: Any) -> str:
    """Render arguments to a deterministic string for hashing."""
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_stable_repr(v) for v in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items())
        return "{" + ",".join(f"{k}={_stable_repr(v)}" for k, v in items) + "}"
    return repr(value)


def _make_key(func_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    payload = func_name + "|" + _stable_repr(args) + "|" + _stable_repr(kwargs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_cache(path: Path, ttl_seconds: int) -> tuple[bool, Any]:
    if not path.exists():
        return False, None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None
    written = envelope.get("written_at", 0)
    if time.time() - written > ttl_seconds:
        return False, None
    return True, _decode(envelope.get("value"))


def _write_cache(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"written_at": time.time(), "value": value}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(envelope, cls=_CacheEncoder), encoding="utf-8")
    tmp.replace(path)


def _resolve_base_dir(explicit: Path | None) -> Path:
    """Re-resolve the cache directory at call time.

    Tests monkeypatch ``DEFAULT_CACHE_DIR`` to redirect writes into a
    pytest tmp_path; resolving lazily means the patch takes effect even
    for decorators that ran at import time.
    """
    if explicit is not None:
        return explicit
    # Re-import attribute lookup so monkeypatched values win.
    import src.data.cache as _self

    return _self.DEFAULT_CACHE_DIR


def cached(
    ttl_seconds: int,
    *,
    cache_dir: Path | None = None,
    namespace: str | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Cache a function's return value to disk for ``ttl_seconds``.

    Works for both sync and async callables. The first positional arg
    (typically ``self``) is excluded from the cache key so methods on
    distinct adapter instances share entries.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        is_coro = inspect.iscoroutinefunction(func)
        ns = namespace or f"{func.__module__}.{func.__qualname__}"

        def cache_path_for(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Path:
            # Drop the bound instance so cache keys aren't tied to id(self).
            key_args = args[1:] if args and not isinstance(args[0], (str, int, float)) else args
            key = _make_key(ns, key_args, kwargs)
            base_dir = _resolve_base_dir(cache_dir)
            return base_dir / ns / f"{key}.json"

        if is_coro:

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> T:
                path = cache_path_for(args, kwargs)
                hit, value = _read_cache(path, ttl_seconds)
                if hit:
                    return cast(T, value)
                coro = cast(Awaitable[T], func(*args, **kwargs))
                result = await coro
                _write_cache(path, result)
                return result

            async_wrapper.cache_path_for = cache_path_for  # type: ignore[attr-defined]
            return cast(Callable[..., T], async_wrapper)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            path = cache_path_for(args, kwargs)
            hit, value = _read_cache(path, ttl_seconds)
            if hit:
                return cast(T, value)
            result = func(*args, **kwargs)
            _write_cache(path, result)
            return result

        sync_wrapper.cache_path_for = cache_path_for  # type: ignore[attr-defined]
        return sync_wrapper

    return decorator


def clear_cache(cache_dir: Path | None = None) -> int:
    """Remove every cached entry under ``cache_dir``. Returns the count removed."""
    base = cache_dir or DEFAULT_CACHE_DIR
    if not base.exists():
        return 0
    removed = 0
    for path in base.rglob("*.json"):
        path.unlink(missing_ok=True)
        removed += 1
    return removed


__all__ = ["DEFAULT_CACHE_DIR", "cached", "clear_cache"]

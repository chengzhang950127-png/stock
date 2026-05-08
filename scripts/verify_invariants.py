"""
Static verification of architectural invariants. CI runs this on every PR.

Each check matches the corresponding numbered invariant in
``docs/INVARIANTS.md``. Adding or removing checks here MUST be paired with
an update to that document so the two stay in lock-step.

Exit code 0 = all clean, 1 = at least one invariant violated.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


# ---- Helpers ----


def _iter_py_files(roots: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(p for p in root.rglob("*.py") if p.is_file())
    return files


def _grep(files: Iterable[Path], pattern: re.Pattern[str]) -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append((f, lineno, line.rstrip()))
    return hits


def _format_hits(hits: list[tuple[Path, int, str]]) -> str:
    return "\n".join(f"  {p.relative_to(ROOT)}:{ln}  {text}" for p, ln, text in hits)


# ---- Invariant checks ----


LLM_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(?:litellm|openai|anthropic)\b|import\s+(?:litellm|openai|anthropic)\b)"
)


def check_invariant_1() -> list[str]:
    """#1 — decision-path modules must not import LLM libraries."""
    decision_roots = [
        SRC / "strategies",
        SRC / "portfolio",
        SRC / "assistant",  # except for narrative.py / news_parser.py once they exist
    ]
    files = _iter_py_files(decision_roots)
    hits = _grep(files, LLM_IMPORT_RE)
    # Permit two named modules where AI is allowed (placeholder paths — created in WP-2.5 / WP-3.4).
    allowed_suffixes = {
        "src/assistant/narrative.py",
        "src/strategies/event_driven_news.py",
    }
    hits = [h for h in hits if h[0].relative_to(ROOT).as_posix() not in allowed_suffixes]
    if hits:
        return [
            "INVARIANT #1 violated — LLM imports on the decision path:",
            _format_hits(hits),
        ]
    return []


def check_invariant_2() -> list[str]:
    """#2 — only ``src/llm/`` may import LLM libraries directly."""
    files = [
        f
        for f in _iter_py_files([SRC])
        if not f.relative_to(ROOT).as_posix().startswith("src/llm/")
    ]
    hits = _grep(files, LLM_IMPORT_RE)
    if hits:
        return [
            "INVARIANT #2 violated — direct LLM import outside src/llm/:",
            _format_hits(hits),
        ]
    return []


COMPLETE_CALL_RE = re.compile(r"\.complete\s*\(")
RESPONSE_SCHEMA_KW_RE = re.compile(r"response_schema\s*[=:]")


def check_invariant_3() -> list[str]:
    """#3 — every ``.complete(...)`` callsite must include ``response_schema``."""
    files = _iter_py_files([SRC])
    bad: list[tuple[Path, int, str]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        # Walk char-by-char and find every .complete(...) call, then look at
        # the parenthesized body for response_schema=.
        for m in COMPLETE_CALL_RE.finditer(text):
            start = m.end()  # index after '('
            # Walk to the matching ')'
            depth = 1
            i = start
            while i < len(text) and depth > 0:
                ch = text[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                i += 1
            body = text[start : i - 1]
            if not RESPONSE_SCHEMA_KW_RE.search(body):
                # Skip the abstract method def and known scaffolding.
                if "abstractmethod" in text[max(0, m.start() - 200) : m.start()]:
                    continue
                # Find line number of the call.
                lineno = text[: m.start()].count("\n") + 1
                line = text.splitlines()[lineno - 1].rstrip()
                bad.append((f, lineno, line))
    if bad:
        return [
            "INVARIANT #3 violated — .complete() call missing response_schema:",
            _format_hits(bad),
        ]
    return []


UNDATED_MODEL_RE = re.compile(
    r'model\s*=\s*"(claude-3-5-sonnet|claude-3-opus|claude-3-haiku|gpt-4|gpt-4o|gpt-3\.5-turbo)"'
)


def check_invariant_4() -> list[str]:
    """#4 — model ids must include a dated suffix."""
    files = _iter_py_files([SRC])
    hits = _grep(files, UNDATED_MODEL_RE)
    if hits:
        return [
            "INVARIANT #4 violated — model id without dated suffix:",
            _format_hits(hits),
        ]
    return []


NONZERO_TEMP_RE = re.compile(r"temperature\s*=\s*(?!0\.0|0(?!\d))[^,\)\s]+")


def check_invariant_5() -> list[str]:
    """#5 — LLM temperature is 0.0 (allow defaults via the param signature itself)."""
    # Only check src/llm/ assignments; downstream code goes through the gateway anyway.
    files = _iter_py_files([SRC / "llm"])
    bad: list[tuple[Path, int, str]] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            # Skip the function signature default in gateway.py (temperature: float = 0.0)
            # and assignments equal to 0.0.
            if NONZERO_TEMP_RE.search(line) and "= 0.0" not in stripped:
                # Also skip ``temperature=temperature`` pass-throughs.
                if re.search(r"temperature\s*=\s*temperature\b", line):
                    continue
                bad.append((f, lineno, stripped))
    if bad:
        return [
            "INVARIANT #5 violated — non-zero temperature in src/llm/:",
            _format_hits(bad),
        ]
    return []


def check_invariant_6() -> list[str]:
    """#6 — every Strategy subclass implements the four abstract methods.

    Phase 0 has no concrete strategies, so this is a no-op import check that
    confirms ``StrategyBase`` is well-formed.
    """
    sys.path.insert(0, str(ROOT))
    try:
        from src.strategies.base import StrategyBase

        required = {"screen", "generate_signals", "exit_rules", "get_score"}
        abstract = set(getattr(StrategyBase, "__abstractmethods__", set()))
        if not required.issubset(abstract):
            return [
                f"INVARIANT #6 violated — StrategyBase missing abstract methods: "
                f"{sorted(required - abstract)}"
            ]
        # Walk concrete subclasses if any exist.
        import importlib
        import pkgutil

        import src.strategies as strategies_pkg

        for _, name, _ in pkgutil.iter_modules(strategies_pkg.__path__):
            mod = importlib.import_module(f"src.strategies.{name}")
            for cls_name in dir(mod):
                cls = getattr(mod, cls_name)
                if (
                    isinstance(cls, type)
                    and issubclass(cls, StrategyBase)
                    and cls is not StrategyBase
                ):
                    missing = required - {
                        m
                        for m in required
                        if getattr(cls, m, None) is not getattr(StrategyBase, m, None)
                    }
                    if missing:
                        return [
                            f"INVARIANT #6 violated — {cls_name} missing implementations: "
                            f"{sorted(missing)}"
                        ]
    finally:
        sys.path.pop(0)
    return []


SECRET_FILE_PATTERNS = ("*.pem", "*.key")


def check_invariant_7() -> list[str]:
    """#7 — no obvious secret files committed; ``.env`` not tracked.

    We check repo file presence (not git history) — git history checks live
    in CI as a separate step (see ``.github/workflows/ci.yml``).
    """
    issues: list[str] = []
    if (ROOT / ".env").exists():
        issues.append("INVARIANT #7 violated — .env file present in working tree")
    for pattern in SECRET_FILE_PATTERNS:
        for hit in ROOT.rglob(pattern):
            # ignore the venv
            if ".venv" in hit.parts:
                continue
            issues.append(f"INVARIANT #7 violated — secret-like file: {hit}")
    return issues


def main() -> int:
    checks = [
        check_invariant_1,
        check_invariant_2,
        check_invariant_3,
        check_invariant_4,
        check_invariant_5,
        check_invariant_6,
        check_invariant_7,
    ]
    failures: list[str] = []
    for check in checks:
        result = check()
        if result:
            failures.extend(result)
            failures.append("")  # blank separator

    if failures:
        sys.stderr.write("\n".join(failures) + "\n")
        return 1
    print("All architectural invariants OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

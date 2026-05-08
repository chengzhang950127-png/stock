# Architectural invariants

These seven invariants are the contract between every Work Package and the
rest of the system. Violating any of them is an automatic review fail. The
numbering and wording here is the canonical reference — `scripts/verify_invariants.py`
mirrors it 1-for-1, and CI runs that script on every PR.

---

## #1 — Decision path contains zero LLM calls

Stock screening, buy / sell pricing, regime classification, asset allocation,
and strategy promotion / demotion are all pure code rules. AI is permitted
in **exactly two** places:

1. News parsing inside the event-driven strategy (`src/strategies/event_driven_news.py`)
2. Narrative generation inside the investment assistant (`src/assistant/narrative.py`)

Both wrap the LLM Gateway, never the underlying SDKs.

**Static check** (also implemented in `scripts/verify_invariants.py`):

```bash
grep -rn 'import litellm\|from openai\|import anthropic' \
  src/strategies/ src/portfolio/ src/assistant/ \
  | grep -v 'src/assistant/narrative.py' \
  | grep -v 'src/strategies/event_driven_news.py'
```

Expected: empty output.

---

## #2 — All LLM calls go through `LLMGateway`

Business code MUST NOT import `openai`, `anthropic`, or `litellm` directly.
Only modules under `src/llm/` may import them.

**Static check:**

```bash
grep -rn 'import litellm\|from openai\|import anthropic' src/ --include='*.py' | grep -v 'src/llm/'
```

Expected: empty output.

---

## #3 — Every LLM output is validated against a Pydantic schema

Every call to `LLMGateway.complete(...)` MUST pass `response_schema=`. The
gateway parses the model's output through that schema and raises
`LLMValidationError` if validation fails. There is no free-text variant on
purpose.

**Static check:**

```bash
grep -rn '\.complete(' src/ | grep -v 'response_schema'
```

Expected: empty output (the abstract method definition itself is whitelisted
by the verifier).

---

## #4 — Pinned dated model ids — no `latest` aliases

Every model id passed to the Gateway must include an unambiguous date suffix
(e.g. `claude-3-5-sonnet-20241022` or `gpt-4o-2024-08-06`). Aliases like
`claude-3-5-sonnet` (no date) drift silently as providers update them.

**Static check:**

```bash
grep -rn 'model="claude-3-5-sonnet"$\|model="gpt-4"$\|model="gpt-4o"$' src/
```

Expected: empty output. The Gateway also rejects un-dated ids at runtime
via `LLMGateway._validate_model_id`.

---

## #5 — `temperature=0.0` by default

LLM calls run at zero temperature unless an explicit, documented exception
exists. This is enforced inside `src/llm/`:

```bash
grep -rn 'temperature=' src/llm/ | grep -v 'temperature=0.0' | grep -v 'temperature=temperature'
```

Expected: empty output (the function-signature default `temperature: float = 0.0`
is allowed because it sets the floor).

---

## #6 — Every `Strategy` subclass implements all four abstract methods

`screen`, `generate_signals`, `exit_rules`, `get_score` are all `@abstractmethod`
on `StrategyBase`. The verifier walks `src/strategies/` and confirms each
concrete subclass overrides each method.

**Programmatic check** (run by `scripts/verify_invariants.py`):

```python
from src.strategies.base import StrategyBase
import importlib, pkgutil
import src.strategies as strategies_pkg

for _, name, _ in pkgutil.iter_modules(strategies_pkg.__path__):
    mod = importlib.import_module(f"src.strategies.{name}")
    for cls_name in dir(mod):
        cls = getattr(mod, cls_name)
        if isinstance(cls, type) and issubclass(cls, StrategyBase) and cls is not StrategyBase:
            for method in ("screen", "generate_signals", "exit_rules", "get_score"):
                assert getattr(cls, method) is not getattr(StrategyBase, method), (
                    f"{cls_name} did not override {method}"
                )
```

---

## #7 — Secrets, broker credentials, and personal positions never enter git

`.gitignore` blocks `.env*`, `*.pem`, `*.key`, `secrets/`, `credentials/`,
`user_data/`, `broker_credentials/`, `positions/`, and `trades/`. CI runs
two extra git-history checks beyond the local verifier:

```bash
git log --all -p | grep -iE "api[_-]?key|secret|password|token" | head -20
git ls-files | grep -E "\.env$"
```

Both are expected to be empty.

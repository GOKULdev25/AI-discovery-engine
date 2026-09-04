"""EV-P3-04 — exhaustion degrades, never fails (A§11.1). Gemini exhausted
routes to Groq; both exhausted routes to Ollama; all three exhausted
surfaces as one typed exception the caller can requeue for later, never
an unhandled crash."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.ai import router
from app.ai.providers import fake
from app.ai.providers.base import ProviderQuotaExhausted
from app.pipeline import classify
from app.store import sqlite as sq
from evals.registry import eval_case

_PROTOTYPES_CONTENT = """\
keep:
  - "The app keeps crashing every time I open it, this really needs to be fixed."
drop:
  - "Buy cheap watches now at this link, limited time offer, click here!"
"""


@eval_case(
    "EV-P3-04",
    proves="Forcing Gemini QUOTA_EXHAUSTED fails over to Groq; forcing both fails over to Ollama; forcing all three requeues instead of crashing",
    source="A§11.1",
    severity="BLOCKER",
    tags=["phase:P3"],
)
async def ev_p3_04():
    with tempfile.TemporaryDirectory(prefix="ev-p304-") as tmp:
        app_sqlite = Path(tmp) / "app.sqlite"
        async with sq.app_db(app_sqlite) as conn:
            # Gemini exhausted -> Groq serves it.
            gemini_empty = fake.gemini_like(script=[])
            groq_ready = fake.groq_like(script=[{"ok": True}])
            result = await router.route(conn, [gemini_empty, groq_ready], "prompt-1")
            assert result.provider_id == "groq"
            assert len(gemini_empty.calls) == 1, "gemini should have been tried (and recorded the attempt) before failing over"
            assert len(groq_ready.calls) == 1

        async with sq.app_db(app_sqlite) as conn:
            # Both exhausted -> Ollama serves it.
            gemini_empty = fake.gemini_like(script=[])
            groq_empty = fake.groq_like(script=[])
            ollama_ready = fake.ollama_like(script=[{"ok": True}])
            result = await router.route(conn, [gemini_empty, groq_empty, ollama_ready], "prompt-2")
            assert result.provider_id == "ollama"

        async with sq.app_db(app_sqlite) as conn:
            # All three exhausted -> one typed exception, not a crash.
            all_empty = [fake.gemini_like(script=[]), fake.groq_like(script=[]), fake.ollama_like(script=[])]
            raised = False
            try:
                await router.route(conn, all_empty, "prompt-3")
            except ProviderQuotaExhausted:
                raised = True
            assert raised, "router.route must raise ProviderQuotaExhausted, not silently return, when every provider is exhausted"

        # And the layer above the router — pipeline/classify.py — turns
        # that exception into "this batch stays ambiguous", never an
        # unhandled crash of the classify loop itself.
        docs = [{"doc_id": f"d{i}", "text": f"a genuinely unique review body number {i} about the product"} for i in range(5)]
        with tempfile.TemporaryDirectory(prefix="ev-p304b-") as tmp2:
            prototypes_path = Path(tmp2) / "prototypes.yaml"
            prototypes_path.write_text(_PROTOTYPES_CONTENT, encoding="utf-8")
            providers = [fake.gemini_like(script=[]), fake.groq_like(script=[]), fake.ollama_like(script=[])]
            async with sq.app_db(app_sqlite) as conn:
                resolved = await classify.classify_batch(conn, providers, prototypes_path, docs)
            assert resolved == [], "with every provider exhausted, nothing should be resolved — it stays ambiguous for the next tick"

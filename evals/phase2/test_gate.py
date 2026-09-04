"""EV-P2-06 — with prototypes loaded, the gate's ambiguous band stays a
minority of documents. If it isn't, the prototypes are wrong and Phase
3's LLM cost model (only the ambiguous band reaches an API) breaks.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.pipeline import enrich_local, gate
from app.projects import scaffold
from evals.registry import eval_case

# A realistic-shaped mixed corpus: clearly matches "keep" (real reviews),
# clearly matches "drop" (spam/boilerplate), and a couple of genuinely
# borderline documents.
_CORPUS = [
    "The app crashes every single time I try to open the camera, please fix this bug soon.",
    "I absolutely love this app, it saves me so much time every single day at work.",
    "Battery drain is terrible since the last update, my phone dies by noon now.",
    "Customer support never responded to my ticket about the login issue for weeks.",
    "Buy cheap watches now at www.totallylegit-deals.example!!! Limited time offer!!!",
    "This thread has been locked by a moderator for violating community guidelines.",
    "Subscribe to my channel for more content like this, link in bio.",
    "Meh.",
]


@eval_case(
    "EV-P2-06",
    proves="The gate's cost model holds: on a realistic mixed corpus the ambiguous band is a minority of documents",
    source="A§11.2",
    severity="MAJOR",
    tags=["phase:P2"],
)
async def ev_p2_06():
    with tempfile.TemporaryDirectory(prefix="ev-p206-") as tmp:
        # The actual starter file every new project ships with (scaffold.py)
        # — this eval exists precisely to keep that default's prototype
        # *style* (concrete examples, not category descriptions) honest
        # against the real decision margin, not a hand-tuned copy that can
        # drift from what users actually get (EV-P2-06).
        prototypes_path = Path(tmp) / "prototypes.yaml"
        prototypes_path.write_text(scaffold._STARTER_PROTOTYPES, encoding="utf-8")

        vectors = await enrich_local.embed_texts(_CORPUS)
        rows = [{"doc_id": str(i), "text": text, "vector": vec} for i, (text, vec) in enumerate(zip(_CORPUS, vectors))]

        results = await gate.gate_documents(rows, prototypes_path)
        bands = [r["gate_band"] for r in results]
        ambiguous_fraction = bands.count("ambiguous") / len(bands)

        assert ambiguous_fraction < 0.25, (
            f"ambiguous band is {ambiguous_fraction:.0%} of the corpus (budget: <25%) — "
            f"prototypes need work: {list(zip(_CORPUS, bands))}"
        )
        # And the obvious cases should land where a human would put them.
        by_text = dict(zip(_CORPUS, bands))
        assert by_text["Buy cheap watches now at www.totallylegit-deals.example!!! Limited time offer!!!"] in ("drop", "ambiguous")
        assert by_text["I absolutely love this app, it saves me so much time every single day at work."] in ("keep", "ambiguous")

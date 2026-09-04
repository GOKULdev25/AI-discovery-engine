"""The one place allowed to read environment variables or bake in a default
filesystem root, a default host, or a default port (IP§0.1 rule 3;
EV-INV-03, EV-INV-04). Every other module receives paths and settings
through this object, never through os.environ or a literal path.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Filesystem roots ---
    data_root: Path = Path("./data")
    projects_root_override: Path | None = None

    # --- API ---
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_base_url: str = "http://127.0.0.1:8000"
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- Job engine ---
    worker_count: int = 4
    stale_claim_seconds: int = 120
    sse_heartbeat_seconds: int = 15
    max_batch_links: int = 500

    # A retryable failure means "backoff and requeue" (A§8.1), not "retry
    # forever" — these bound the automatic loop before a job surfaces as a
    # terminal failure that an explicit POST /retry can still pick up later.
    max_retryable_attempts: int = 5
    retry_backoff_base_seconds: float = 1.0
    retry_backoff_max_seconds: float = 60.0

    # How often staged docs drain into the warehouse (A§9 committer). A
    # DuckDB commit has a large fixed cost regardless of row count, so this
    # batches many jobs' worth of docs into one commit rather than one
    # commit per completed job.
    drain_interval_seconds: float = 0.25

    # --- Per-source concurrency (A§10.2 defaults; overridable per project via
    # project.yaml rate_overrides, never by editing this file per-project) ---
    youtube_concurrency: int = 4
    appstore_concurrency: int = 3
    reddit_concurrency: int = 2
    playstore_concurrency: int = 2
    browser_concurrency: int = 1  # structural ceiling — never raised (A§4)
    # A real, visible Chrome window by default (A§5.1 — "nothing to spoof,
    # because nothing is fake"). The eval harness forces this True so the
    # automatic suite never pops up a window; a `live` browser eval or
    # real batch submission runs it headful.
    browser_headless: bool = False
    # A§5.1's CDP-attach path for `operator_session` — the operator starts
    # Chrome themselves with `--remote-debugging-port=<this port>` and
    # signs in manually; this app never sees a credential either way.
    operator_cdp_url: str = "http://127.0.0.1:9222"
    # A§14: "the browser lane never moves to a free cloud host" — free
    # tiers provide no real desktop Chrome with a persistent profile, and
    # Lane 2 is headful by design. On such a host this is set False, so a
    # Flipkart/Amazon/Myntra link fails immediately with a typed,
    # explained `UNSUPPORTED_SOURCE` instead of hanging on a browser that
    # is never going to launch. Fail loudly (P§6), not slowly.
    browser_lane_enabled: bool = True

    # --- Degradation switches for constrained hosts ---
    # The fastembed ONNX model (bge-small, A§6) plus onnxruntime is over
    # half of a 512MB instance on its own. Setting this False skips the
    # model entirely: retrieval degrades to BM25-only (the lexical half of
    # A§12's hybrid stays exact), and gate stage 2 stops voting, so
    # everything the lexical prefilter didn't settle reaches stage 3 as
    # honestly `ambiguous` (A§11.2) rather than being guessed at locally.
    # That is a visible *cost* change — more documents reach the LLM — not
    # a silent quality one, and `GET /quota` shows it happening.
    embeddings_enabled: bool = True

    # --- Provider credentials (Phase -1) ---
    youtube_api_key: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "ai-discovery-engine/0.1"
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"

    # --- AI layer (Phase 3) — model IDs are settings, not literals, so a
    # provider's model naming can move without a code change ---
    gemini_model: str = "gemini-3.6-flash"
    groq_model: str = "allam-2-7b"
    ollama_model: str = "llama3.1"
    classify_batch_size: int = 25  # ~25 docs/request keeps Gemini bulk classification inside its RPD ceiling (A§11.1)
    classify_interval_seconds: float = 5.0  # how often each project polls for newly-ambiguous documents
    # Defaults on for real use; the eval harness forces this off (mirroring
    # `warmup_models=False`) so that spinning up an ordinary ProjectEngine
    # for an unrelated Phase 0-2 eval can never trigger a live Gemini/Groq
    # call just because `.env`'s real keys loaded into that eval's Settings
    # (EV-INV-14 — an automatic eval run must spend zero free-tier requests).
    ai_classification_enabled: bool = True

    @property
    def projects_root(self) -> Path:
        return self.projects_root_override or (self.data_root / "projects")

    @property
    def app_sqlite_path(self) -> Path:
        return self.data_root / "app.sqlite"


@lru_cache
def get_settings() -> Settings:
    return Settings()

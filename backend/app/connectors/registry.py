"""One line per connector (A§10.1). Adding a fifth source means importing
it and appending it here — nothing else changes (EV-P1-10).
"""

from __future__ import annotations

from app.browser.sites.amazon import AmazonConnector
from app.browser.sites.flipkart import FlipkartConnector
from app.browser.sites.myntra import MyntraConnector
from app.connectors.base import Connector, JobSpec
from app.connectors._fixture import FixtureConnector
from app.connectors.appstore import AppStoreConnector
from app.connectors.playstore import PlayStoreConnector
from app.connectors.reddit import RedditConnector
from app.connectors.youtube import YouTubeConnector
from app.fallback.llm_dom import LLMDomConnector

_CONNECTORS: list[Connector] = [
    FixtureConnector(),
    AppStoreConnector(),
    PlayStoreConnector(),
    YouTubeConnector(),
    RedditConnector(),
    # Lane 2 (browser) — checked only once no Lane 1 connector matches, so
    # these never compete with a real API connector for the same URL
    # (A§4's lane-selection order).
    FlipkartConnector(),
    AmazonConnector(),
    MyntraConnector(),
    # Lane 3 (P7, A§4) — last resort: only reached once nothing above
    # claims the URL. Can still decline (a binary asset, a bad scheme),
    # which correctly falls through to `UNSUPPORTED_SOURCE` exactly like
    # any other connector's decline (EV-P7-05).
    LLMDomConnector(),
]


def all_connectors() -> list[Connector]:
    return list(_CONNECTORS)


def classify(url: str) -> tuple[Connector, JobSpec] | None:
    """Returns the first connector that matches `url`, or None (Lane 3 /
    UNSUPPORTED_SOURCE territory — P7)."""
    for connector in _CONNECTORS:
        job = connector.match(url)
        if job is not None:
            return connector, job
    return None


def get_by_id(connector_id: str) -> Connector | None:
    for connector in _CONNECTORS:
        if connector.id == connector_id:
            return connector
    return None

"""Canned, realistic response payloads for the Phase 1 golden-batch eval —
shapes captured from real live calls during Phase 1 development (see
`Docs/FEASIBILITY_LOG.md`, 2026-08-29), not guessed. This is this
project's cassette equivalent: recorded, deterministic, offline
(EVAL.md §3.4) — organized as importable Python data rather than VCR-style
JSON files, since the connectors' own request shapes (query params, not
request bodies) make that the lower-friction fixture format here.
"""

from __future__ import annotations

APPSTORE_PAGE_1 = {
    "feed": {
        "entry": [
            {
                "author": {"name": {"label": "reviewer_one"}},
                "updated": {"label": "2026-08-20T10:00:00-07:00"},
                "im:rating": {"label": "5"},
                "im:version": {"label": "1.0"},
                "id": {"label": "1001"},
                "title": {"label": "Great app"},
                "content": {"label": "Works perfectly for me."},
                "im:voteSum": {"label": "2"},
                "im:voteCount": {"label": "3"},
            },
            {
                "author": {"name": {"label": "reviewer_two"}},
                "updated": {"label": "2026-08-19T09:00:00-07:00"},
                "im:rating": {"label": "1"},
                "im:version": {"label": "1.0"},
                "id": {"label": "1002"},
                "title": {"label": "Crashes constantly"},
                "content": {"label": "App crashes on launch every time."},
                "im:voteSum": {"label": "0"},
                "im:voteCount": {"label": "0"},
            },
        ]
    }
}

APPSTORE_PAGE_EMPTY = {"feed": {"author": {"name": {"label": "iTunes Store"}}}}

APPSTORE_MALFORMED_TEXT = "<html>not json</html>"

PLAYSTORE_PAGE_1 = [
    {
        "reviewId": "r-en-1", "userName": "alice", "content": "Love it",
        "score": 5, "thumbsUpCount": 1, "at": None, "appVersion": "2.0",
    },
    {
        "reviewId": "r-en-2", "userName": "bob", "content": "Battery drain issue",
        "score": 2, "thumbsUpCount": 0, "at": None, "appVersion": "2.0",
    },
]

YOUTUBE_PAGE_1 = {
    "items": [
        {
            "snippet": {
                "videoId": "abc123",
                "topLevelComment": {
                    "id": "c1",
                    "snippet": {
                        "authorDisplayName": "commenter1",
                        "authorChannelId": {"value": "UC_commenter1"},
                        "textOriginal": "Nice video!",
                        "likeCount": 4,
                        "publishedAt": "2026-08-15T12:00:00Z",
                    },
                },
                "totalReplyCount": 1,
            },
            "replies": {
                "comments": [
                    {
                        "id": "c1-r1",
                        "snippet": {
                            "authorDisplayName": "commenter2",
                            "authorChannelId": {"value": "UC_commenter2"},
                            "textOriginal": "Agreed!",
                            "likeCount": 1,
                            "publishedAt": "2026-08-15T13:00:00Z",
                        },
                    }
                ]
            },
        }
    ],
    "nextPageToken": None,
}

YOUTUBE_QUOTA_EXCEEDED_BODY = (
    '{"error": {"code": 403, "errors": [{"reason": "quotaExceeded", '
    '"message": "The request cannot be completed because you have exceeded your quota."}]}}'
)

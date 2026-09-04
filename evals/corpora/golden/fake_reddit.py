"""A minimal fake standing in for `asyncpraw.Reddit` — just the surface
`connectors/reddit.py` actually touches. Avoids needing a real OAuth
handshake (asyncpraw's own networking) for an offline, deterministic test.
"""

from __future__ import annotations


class _FakeAuthor:
    def __init__(self, name: str):
        self.name = name


class _FakeCommentList(list):
    def list(self):
        return list(self)


class _FakeReplies:
    def __init__(self, comments: list["_FakeComment"]):
        self._comments = comments

    async def replace_more(self, limit=None):
        return []

    def list(self):
        return list(self._comments)


class _FakeComment:
    def __init__(self, id_: str, author: str, body: str, score: int, parent_id: str, permalink: str):
        self.id = id_
        self.author = _FakeAuthor(author)
        self.body = body
        self.score = score
        self.parent_id = parent_id
        self.permalink = permalink
        self.created_utc = 1755600000.0


class _FakeSubmission:
    def __init__(self, id_: str, title: str, selftext: str, author: str, permalink: str, comments: list[_FakeComment]):
        self.id = id_
        self.title = title
        self.selftext = selftext
        self.author = _FakeAuthor(author)
        self.permalink = permalink
        self.score = 42
        self.num_comments = len(comments)
        self.created_utc = 1755500000.0
        self.comments = _FakeReplies(comments)


class FakeReddit:
    """Drop-in for `asyncpraw.Reddit(...)` in tests — same constructor
    signature (ignored), same `submission()`/`close()` surface."""

    def __init__(self, *args, submission: _FakeSubmission | None = None, raise_exc: Exception | None = None, **kwargs):
        self._submission = submission
        self._raise_exc = raise_exc
        self.closed = False

    async def submission(self, id=None, *, fetch=True, url=None):
        if self._raise_exc:
            raise self._raise_exc
        return self._submission

    async def close(self):
        self.closed = True


def make_fake_submission() -> _FakeSubmission:
    top = _FakeComment("t1", "top_author", "First take.", 5, "t3_post1", "/r/test/comments/post1/_/t1/")
    reply = _FakeComment("t2", "reply_author", "I disagree.", 1, "t1_t1", "/r/test/comments/post1/_/t2/")
    return _FakeSubmission(
        id_="post1", title="A discussion thread", selftext="What do you all think?",
        author="op_author", permalink="/r/test/comments/post1/a_discussion_thread/",
        comments=[top, reply],
    )

"""Call-count usage tracking: wraps any Anthropic-shaped client and tallies
how many API calls a run made, by model, so a run's result can report a
usage meter. This is interim, call-count-only visibility -- real token/
dollar cost tracking is Milestone 2 work, not built here (see ROADMAP.md).

Originally lived inline in app.py (the admin console's usage meter); moved
here so batch.py's real-pilot runs can reuse the exact same wrapper for
Stage 6's admin dashboard instead of duplicating it.
"""


class _CountingMessages:
    def __init__(self, inner, counter):
        self._inner = inner
        self._counter = counter

    async def create(self, **kwargs):
        model = kwargs.get("model", "?")
        self._counter["total"] += 1
        by_model = self._counter["by_model"]
        by_model[model] = by_model.get(model, 0) + 1
        return await self._inner.create(**kwargs)


class CountingClient:
    def __init__(self, inner):
        self.counter = {"total": 0, "by_model": {}}
        self.messages = _CountingMessages(inner.messages, self.counter)

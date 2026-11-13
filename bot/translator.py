"""English -> Uzbek word translations, cached in the database.

Uses Google Translate's keyless web endpoint (the one browser extensions use).
It is unofficial, so every failure is tolerated: the word is simply shown
without a translation and retried next time. Admin corrections (/tr) are
stored with source='admin' and are never overwritten.
"""
import asyncio
import logging

import aiohttp

from .db import Database

log = logging.getLogger(__name__)

URL = "https://translate.googleapis.com/translate_a/single"
MAX_MEANINGS = 3


def format_translation(word: str, data) -> str | None:
    """Main translation plus other meanings, one per part of speech first.

    data[0] holds the sentence translation, data[1] (if present) the dictionary
    entries: [[part_of_speech, [term, ...], ...], ...]
    """
    if not (isinstance(data, list) and data and isinstance(data[0], list)):
        return None
    main = "".join(p[0] for p in data[0] if isinstance(p, list) and p and isinstance(p[0], str)).strip()
    groups: list[list[str]] = []
    if len(data) > 1 and isinstance(data[1], list):
        for entry in data[1]:
            if isinstance(entry, list) and len(entry) > 1 and isinstance(entry[1], list):
                groups.append([t for t in entry[1] if isinstance(t, str) and t.strip()])
    meanings: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        key = term.strip().lower()
        if key and key not in seen and len(meanings) < MAX_MEANINGS:
            seen.add(key)
            meanings.append(term.strip())

    if main and main.lower() != word:
        add(main)
    for i in range(max((len(g) for g in groups), default=0)):   # round-robin over parts of speech
        for g in groups:
            if i < len(g):
                add(g[i])
    if not meanings and main:
        meanings.append(main)                                  # e.g. "pizza" -> "pizza"
    return ", ".join(meanings) or None


class Translator:
    def __init__(self, db: Database, *, timeout: float = 4.0, concurrency: int = 4) -> None:
        self.db = db
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._sem = asyncio.Semaphore(concurrency)
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def translate_many(self, words: list[str]) -> dict[str, str]:
        words = list(dict.fromkeys(words))
        found = await self.db.get_translations(words)
        missing = [w for w in words if w not in found]
        if missing:
            fetched = await asyncio.gather(*(self._fetch(w) for w in missing))
            for word, uz in zip(missing, fetched):
                if uz:
                    found[word] = uz
                    await self.db.save_translation(word, uz, "google")
        return found

    async def _fetch(self, word: str) -> str | None:
        params = [("client", "gtx"), ("sl", "en"), ("tl", "uz"), ("dt", "t"), ("dt", "bd"), ("q", word)]
        try:
            async with self._sem:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession(timeout=self._timeout)
                async with self._session.get(URL, params=params) as resp:
                    if resp.status != 200:
                        log.warning("translate %r: HTTP %s", word, resp.status)
                        return None
                    data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            log.warning("translate %r failed: %s", word, e)
            return None
        return format_translation(word, data)

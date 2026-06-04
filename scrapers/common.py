"""Shared utilities: schema, model detection, dedup, NDJSON I/O."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRAPER_VERSION = "1.0"


@dataclass
class Record:
    source: str
    source_subkey: str
    post_id: str
    permalink: str
    date: str
    model_mentioned: str
    post_text: str
    score: int
    is_comment: bool
    parent_id: str | None
    mentions_release_event: str | None
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    scraper_version: str = SCRAPER_VERSION


def utc_iso_from_unix(ts: int | float) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


# --- Model detection ---------------------------------------------------------

_MODEL_KEYWORDS_CACHE: dict[str, list[str]] | None = None


def load_model_keywords(config_dir: Path) -> dict[str, list[str]]:
    global _MODEL_KEYWORDS_CACHE
    if _MODEL_KEYWORDS_CACHE is None:
        with open(config_dir / "model_keywords.json") as f:
            _MODEL_KEYWORDS_CACHE = json.load(f)
    return _MODEL_KEYWORDS_CACHE


def _matches_any(text_lower: str, keywords: list[str]) -> bool:
    for kw in keywords:
        kw_lower = kw.lower()
        # Use word-boundary regex for short tokens (≤3 chars) to avoid false positives
        # like "o1" matching "to1k". Substring match is fine for longer tokens.
        if len(kw_lower) <= 3:
            if re.search(rf"\b{re.escape(kw_lower)}\b", text_lower):
                return True
        else:
            if kw_lower in text_lower:
                return True
    return False


def detect_model(
    text: str,
    keywords: dict[str, list[str]],
    parent_model: str | None = None,
) -> str:
    """Return 'claude', 'openai', 'both', or 'unknown'.

    If a `parent_model` is provided AND the text alone yields 'unknown', inherit the
    parent's value. This captures comments that lack the model name in their own text
    but are clearly contextually about the parent post's model.
    """
    text_lower = text.lower()
    has_claude = _matches_any(text_lower, keywords.get("claude", []))
    has_openai = _matches_any(text_lower, keywords.get("openai", []))
    if has_claude and has_openai:
        return "both"
    if has_claude:
        return "claude"
    if has_openai:
        return "openai"
    if parent_model and parent_model != "unknown":
        return parent_model
    return "unknown"


# --- Release detection -------------------------------------------------------

_RELEASES_CACHE: list[dict[str, Any]] | None = None


def load_releases(config_dir: Path) -> list[dict[str, Any]]:
    """Load `verified: true` releases only. Unverified entries are
    placeholders with best-guess dates — rendering them on the trend chart
    or tagging records to them would mislead. Flip `verified: true` in
    config/releases.json after confirming the date against the vendor's
    announcement page.
    """
    global _RELEASES_CACHE
    if _RELEASES_CACHE is None:
        path = config_dir / "releases.json"
        if not path.exists():
            _RELEASES_CACHE = []
        else:
            with open(path) as f:
                data = json.load(f)
            _RELEASES_CACHE = [
                r for r in data.get("releases", []) if r.get("verified") is True
            ]
    return _RELEASES_CACHE


def detect_release_event(
    text: str, post_date_iso: str, releases: list[dict[str, Any]]
) -> str | None:
    """Match by label/version mention OR within 14 days post-release."""
    if not releases:
        return None
    text_lower = text.lower()
    for release in releases:
        label = (release.get("label") or "").lower()
        version = (release.get("version") or "").lower()
        if label and label in text_lower:
            return release.get("id")
        if version and len(version) >= 3 and version in text_lower:
            return release.get("id")
    try:
        post_dt = datetime.fromisoformat(post_date_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    for release in releases:
        rel_date = release.get("date") or ""
        try:
            rel_dt = datetime.fromisoformat(rel_date).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        delta_days = (post_dt - rel_dt).days
        if 0 <= delta_days <= 14:
            return release.get("id")
    return None


# --- NDJSON output -----------------------------------------------------------

def shard_path(corpus_dir: Path, source: str, date_iso: str) -> Path:
    """corpus/<source>/<YYYY-MM>.ndjson, parents created as needed."""
    yyyy_mm = date_iso[:7] if len(date_iso) >= 7 else "unknown"
    out = corpus_dir / source / f"{yyyy_mm}.ndjson"
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def write_record(corpus_dir: Path, record: Record) -> None:
    path = shard_path(corpus_dir, record.source, record.date)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


# --- Dedup -------------------------------------------------------------------

class DedupIndex:
    """SQLite-backed dedup keyed on (source, permalink). Persists across scraper
    invocations within a single Phase 1 run. To re-scrape, delete corpus/.dedup.db
    and corpus/* before running again.

    Inserts are batched into transactions of _BATCH_SIZE rows to avoid
    per-row fsyncs on cold-cache backfills. Call flush() (or close()) to
    commit any buffered rows. Correctness is preserved: single-process /
    single-writer; the in-memory pending set prevents false "not seen" answers
    for rows buffered but not yet committed.
    """

    _BATCH_SIZE = 500

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
              source    TEXT NOT NULL,
              permalink TEXT NOT NULL,
              score     INTEGER NOT NULL,
              PRIMARY KEY (source, permalink)
            )
            """
        )
        self.conn.commit()
        # Rows buffered since the last commit.
        self._pending: list[tuple[str, str, int]] = []
        # In-memory set of (source, permalink) for rows buffered but not yet
        # committed, so should_write() answers correctly within a batch.
        self._pending_keys: set[tuple[str, str]] = set()

    def _flush_if_full(self) -> None:
        if len(self._pending) >= self._BATCH_SIZE:
            self.flush()

    def flush(self) -> None:
        """Commit all buffered inserts to the database."""
        if not self._pending:
            return
        self.conn.executemany(
            "INSERT OR IGNORE INTO seen (source, permalink, score) VALUES (?, ?, ?)",
            self._pending,
        )
        self.conn.commit()
        self._pending.clear()
        self._pending_keys.clear()

    def should_write(self, source: str, permalink: str, score: int) -> bool:
        key = (source, permalink)
        # Check in-memory pending set first (rows buffered but not yet committed).
        if key in self._pending_keys:
            return False  # already seen this run — first write wins
        cur = self.conn.execute(
            "SELECT score FROM seen WHERE source = ? AND permalink = ?",
            (source, permalink),
        )
        row = cur.fetchone()
        if row is None:
            self._pending.append((source, permalink, score))
            self._pending_keys.add(key)
            self._flush_if_full()
            return True
        return False  # already seen — first write wins

    def close(self) -> None:
        self.flush()
        self.conn.close()

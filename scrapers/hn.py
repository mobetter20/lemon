"""HN Algolia scraper.

Pulls stories matching configured queries with points >= threshold, plus all
comments above the configured text-length floor. (HN does not expose comment
scores; we filter by minimum text length to drop trivial replies.)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from .common import (
    DedupIndex,
    Record,
    detect_model,
    detect_release_event,
    load_model_keywords,
    load_releases,
    utc_iso_from_unix,
    write_record,
)

ALGOLIA_BASE = "https://hn.algolia.com/api/v1"


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30))
def _get(url: str, params: dict[str, Any] | None = None) -> dict:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _flatten_comments(item: dict, parent_id: str | None = None) -> Iterator[dict]:
    """Walk an HN item tree, yielding each comment with its immediate parent."""
    own_id = str(item.get("id", ""))
    for child in item.get("children") or []:
        if child.get("type") == "comment" and child.get("text"):
            child["_parent_id"] = parent_id or own_id
            yield child
            yield from _flatten_comments(child, parent_id=str(child["id"]))


def search_stories(query: str, after_ts: int, before_ts: int, min_points: int) -> list[dict]:
    """Algolia search for stories in [after_ts, before_ts), points >= min_points."""
    out: list[dict] = []
    page = 0
    while True:
        params = {
            "query": query,
            "tags": "story",
            "numericFilters": (
                f"points>={min_points},"
                f"created_at_i>={after_ts},"
                f"created_at_i<{before_ts}"
            ),
            "hitsPerPage": 1000,
            "page": page,
        }
        data = _get(f"{ALGOLIA_BASE}/search", params=params)
        hits = data.get("hits", [])
        out.extend(hits)
        nb_pages = data.get("nbPages", 0)
        if len(hits) < 1000 or page >= nb_pages - 1:
            break
        page += 1
        time.sleep(0.2)
    return out


def fetch_thread(story_id: int) -> dict:
    return _get(f"{ALGOLIA_BASE}/items/{story_id}")


def scrape_hn(
    corpus_dir: Path,
    config_dir: Path,
    months_back: int = 12,
    dedup: DedupIndex | None = None,
    limit_stories_per_window: int | None = None,
) -> int:
    with open(config_dir / "hn_queries.json") as f:
        cfg = json.load(f)
    queries: list[str] = cfg["queries"]
    min_points: int = cfg.get("min_points", 20)
    comment_min_len: int = cfg.get("comment_min_text_length", 20)

    keywords = load_model_keywords(config_dir)
    releases = load_releases(config_dir)

    now = datetime.now(timezone.utc)
    n_records = 0
    seen_story_ids: set[str] = set()

    for q in queries:
        for month_offset in range(months_back):
            window_end = now - timedelta(days=30 * month_offset)
            window_start = window_end - timedelta(days=30)
            after_ts = int(window_start.timestamp())
            before_ts = int(window_end.timestamp())

            print(
                f"[hn] q={q!r} window={window_start.date()}..{window_end.date()}",
                flush=True,
            )
            try:
                stories = search_stories(q, after_ts, before_ts, min_points)
            except Exception as e:
                print(f"  search failed: {e}")
                continue

            if limit_stories_per_window:
                stories = stories[:limit_stories_per_window]

            for story in stories:
                sid = str(story.get("objectID") or story.get("id") or "")
                if not sid or sid in seen_story_ids:
                    continue
                seen_story_ids.add(sid)

                permalink = f"https://news.ycombinator.com/item?id={sid}"
                date_iso = utc_iso_from_unix(story.get("created_at_i", 0))
                title = story.get("title") or ""
                story_text = story.get("story_text") or ""
                full_text = f"{title}\n\n{story_text}".strip()
                points = story.get("points", 0) or 0

                if dedup and not dedup.should_write("hn", permalink, points):
                    continue

                story_model = detect_model(full_text, keywords)
                write_record(
                    corpus_dir,
                    Record(
                        source="hn",
                        source_subkey=f"hn-thread-{sid}",
                        post_id=sid,
                        permalink=permalink,
                        date=date_iso,
                        model_mentioned=story_model,
                        post_text=full_text,
                        score=points,
                        is_comment=False,
                        parent_id=None,
                        mentions_release_event=detect_release_event(
                            full_text, date_iso, releases
                        ),
                    ),
                )
                n_records += 1

                # Comments
                try:
                    thread = fetch_thread(int(sid))
                except Exception as e:
                    print(f"  thread fetch failed for {sid}: {e}")
                    continue

                for comment in _flatten_comments(thread):
                    cid = str(comment.get("id", ""))
                    ctext = (comment.get("text") or "").strip()
                    if len(ctext) < comment_min_len:
                        continue
                    cpermalink = f"https://news.ycombinator.com/item?id={cid}"
                    cdate = utc_iso_from_unix(comment.get("created_at_i", 0))
                    # HN comments have no score; use 0
                    if dedup and not dedup.should_write("hn", cpermalink, 0):
                        continue

                    write_record(
                        corpus_dir,
                        Record(
                            source="hn",
                            source_subkey=f"hn-thread-{sid}",
                            post_id=cid,
                            permalink=cpermalink,
                            date=cdate,
                            model_mentioned=detect_model(ctext, keywords, parent_model=story_model),
                            post_text=ctext,
                            score=0,
                            is_comment=True,
                            parent_id=str(comment.get("_parent_id") or sid),
                            mentions_release_event=detect_release_event(
                                ctext, cdate, releases
                            ),
                        ),
                    )
                    n_records += 1

                time.sleep(0.1)

            time.sleep(0.2)

    print(f"[hn] total records: {n_records}", flush=True)
    return n_records

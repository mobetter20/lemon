"""Reddit historical scraper (pullpush.io primary, arctic_shift fallback).

Strategy: pull all submissions in each (subreddit, month) window, then keep the
top-N% by score with an absolute floor. Then fetch comments above the configured
score floor for each kept post.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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

PULLPUSH_SUBMISSIONS = "https://api.pullpush.io/reddit/search/submission/"
PULLPUSH_COMMENTS = "https://api.pullpush.io/reddit/search/comment/"
ARCTIC_SUBMISSIONS = "https://arctic-shift.photon-reddit.com/api/posts/search"
ARCTIC_COMMENTS = "https://arctic-shift.photon-reddit.com/api/comments/search"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def _get(url: str, params: dict[str, Any] | None = None, timeout: int = 60) -> dict:
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _submissions_endpoint(use_arctic_shift: bool) -> str:
    return ARCTIC_SUBMISSIONS if use_arctic_shift else PULLPUSH_SUBMISSIONS


def _comments_endpoint(use_arctic_shift: bool) -> str:
    return ARCTIC_COMMENTS if use_arctic_shift else PULLPUSH_COMMENTS


def search_submissions(
    subreddit: str,
    after_ts: int,
    before_ts: int,
    use_arctic_shift: bool = False,
) -> list[dict]:
    """Page newest-first through the time window."""
    endpoint = _submissions_endpoint(use_arctic_shift)
    out: list[dict] = []
    cursor_before = before_ts
    while True:
        params = {
            "subreddit": subreddit,
            "after": after_ts,
            "before": cursor_before,
            "size": 100,
            "sort": "desc",
            "sort_type": "created_utc",
        }
        try:
            data = _get(endpoint, params=params)
        except Exception as e:
            print(f"  [reddit_hist] {endpoint} failed: {e}")
            break
        hits = data.get("data", []) or []
        if not hits:
            break
        out.extend(hits)
        oldest = min((h.get("created_utc", before_ts) for h in hits), default=before_ts)
        if oldest <= after_ts or len(hits) < 100:
            break
        cursor_before = oldest
        time.sleep(0.5)
    return out


def filter_top_percentile(posts: list[dict], top_pct: int, floor: int) -> list[dict]:
    """Keep top-N% by score, with absolute score floor."""
    if not posts:
        return []
    sorted_posts = sorted(posts, key=lambda p: p.get("score", 0), reverse=True)
    cutoff_idx = max(1, int(len(sorted_posts) * top_pct / 100))
    threshold_score = sorted_posts[cutoff_idx - 1].get("score", 0)
    threshold = max(threshold_score, floor)
    return [p for p in sorted_posts if (p.get("score", 0) or 0) >= threshold]


def fetch_comments(post_id: str, use_arctic_shift: bool = False) -> list[dict]:
    endpoint = _comments_endpoint(use_arctic_shift)
    params = {"link_id": post_id, "size": 1000}
    try:
        data = _get(endpoint, params=params)
        return data.get("data", []) or []
    except Exception as e:
        print(f"  [reddit_hist] comments fetch failed for {post_id}: {e}")
        return []


def scrape_reddit_historical(
    corpus_dir: Path,
    config_dir: Path,
    months_back: int = 12,
    dedup: DedupIndex | None = None,
    use_arctic_shift: bool = False,
) -> int:
    with open(config_dir / "subreddits.json") as f:
        cfg = json.load(f)
    subs: list[str] = cfg["subreddits"]
    sel = cfg["selection_strategy"]
    top_pct: int = sel.get("top_percentile", 20)
    floor: int = sel.get("min_score_floor", 5)
    comment_floor: int = sel.get("comment_score_floor", 3)

    keywords = load_model_keywords(config_dir)
    releases = load_releases(config_dir)

    now = datetime.now(timezone.utc)
    n_records = 0

    for sub in subs:
        for month_offset in range(months_back):
            window_end = now - timedelta(days=30 * month_offset)
            window_start = window_end - timedelta(days=30)
            after_ts = int(window_start.timestamp())
            before_ts = int(window_end.timestamp())

            print(
                f"[reddit_hist] r/{sub} window={window_start.date()}..{window_end.date()}",
                flush=True,
            )
            posts = search_submissions(
                sub, after_ts, before_ts, use_arctic_shift=use_arctic_shift
            )
            kept = filter_top_percentile(posts, top_pct, floor)
            print(f"  pulled={len(posts)} kept_top_{top_pct}%_floor_{floor}={len(kept)}")

            for p in kept:
                pid = str(p.get("id") or "")
                if not pid:
                    continue
                permalink_path = p.get("permalink") or ""
                permalink = f"https://www.reddit.com{permalink_path}" if permalink_path else f"https://www.reddit.com/r/{sub}/comments/{pid}/"
                date_iso = utc_iso_from_unix(p.get("created_utc", 0))
                title = p.get("title") or ""
                selftext = p.get("selftext") or ""
                full_text = f"{title}\n\n{selftext}".strip()
                score = p.get("score", 0) or 0

                if dedup and not dedup.should_write("reddit", permalink, score):
                    continue

                write_record(
                    corpus_dir,
                    Record(
                        source="reddit",
                        source_subkey=f"r/{sub}",
                        post_id=pid,
                        permalink=permalink,
                        date=date_iso,
                        model_mentioned=detect_model(full_text, keywords),
                        post_text=full_text,
                        score=score,
                        is_comment=False,
                        parent_id=None,
                        mentions_release_event=detect_release_event(
                            full_text, date_iso, releases
                        ),
                    ),
                )
                n_records += 1

                # Comments
                comments = fetch_comments(f"t3_{pid}", use_arctic_shift=use_arctic_shift)
                for c in comments:
                    cscore = c.get("score", 0) or 0
                    if cscore < comment_floor:
                        continue
                    ctext = c.get("body") or ""
                    if not ctext or ctext in ("[deleted]", "[removed]"):
                        continue
                    cid = str(c.get("id") or "")
                    cperm_path = c.get("permalink") or ""
                    cpermalink = f"https://www.reddit.com{cperm_path}" if cperm_path else f"{permalink}{cid}/"
                    cdate = utc_iso_from_unix(c.get("created_utc", 0))

                    if dedup and not dedup.should_write("reddit", cpermalink, cscore):
                        continue

                    write_record(
                        corpus_dir,
                        Record(
                            source="reddit",
                            source_subkey=f"r/{sub}",
                            post_id=cid,
                            permalink=cpermalink,
                            date=cdate,
                            model_mentioned=detect_model(ctext, keywords),
                            post_text=ctext,
                            score=cscore,
                            is_comment=True,
                            parent_id=str(c.get("parent_id") or pid),
                            mentions_release_event=detect_release_event(
                                ctext, cdate, releases
                            ),
                        ),
                    )
                    n_records += 1

                time.sleep(0.3)

            time.sleep(1.0)

    print(f"[reddit_hist] total records: {n_records}", flush=True)
    return n_records

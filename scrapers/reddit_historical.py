"""Reddit historical scraper — arctic_shift primary, pullpush fallback.

After Phase 1 testing, pullpush.io showed material data gaps for our subreddits
(many windows returned 0 records, and its comments endpoint frequently 5xx'd).
arctic_shift covers the same windows reliably. We use arctic_shift first; on
empty result we retry against pullpush in case arctic_shift has its own gaps.

Strategy: pull all submissions in each (subreddit, month) window, keep the
top-N% by score with an absolute floor, then fetch comments above the score
floor for each kept post. Comments inherit the post's `model_mentioned` when
their own text doesn't trigger detection.
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

ARCTIC_SUBMISSIONS = "https://arctic-shift.photon-reddit.com/api/posts/search"
ARCTIC_COMMENTS = "https://arctic-shift.photon-reddit.com/api/comments/search"
PULLPUSH_SUBMISSIONS = "https://api.pullpush.io/reddit/search/submission/"
PULLPUSH_COMMENTS = "https://api.pullpush.io/reddit/search/comment/"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def _get(url: str, params: dict[str, Any] | None = None, timeout: int = 60) -> dict:
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _arctic_paginate(subreddit: str, after_ts: int, before_ts: int) -> list[dict]:
    out: list[dict] = []
    cursor_before = before_ts
    while True:
        params = {
            "subreddit": subreddit,
            "after": after_ts,
            "before": cursor_before,
            "limit": 100,
            "sort": "desc",
        }
        try:
            data = _get(ARCTIC_SUBMISSIONS, params=params)
        except Exception as e:
            print(f"  [arctic_shift] search failed: {e}")
            break
        hits = data.get("data") or []
        if not hits:
            break
        out.extend(hits)
        oldest = min((h.get("created_utc", before_ts) for h in hits), default=before_ts)
        if oldest <= after_ts or len(hits) < 100:
            break
        cursor_before = int(oldest)
        time.sleep(0.5)
    return out


def _pullpush_paginate(subreddit: str, after_ts: int, before_ts: int) -> list[dict]:
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
            data = _get(PULLPUSH_SUBMISSIONS, params=params)
        except Exception as e:
            print(f"  [pullpush] search failed: {e}")
            break
        hits = data.get("data") or []
        if not hits:
            break
        out.extend(hits)
        oldest = min((h.get("created_utc", before_ts) for h in hits), default=before_ts)
        if oldest <= after_ts or len(hits) < 100:
            break
        cursor_before = int(oldest)
        time.sleep(0.5)
    return out


def search_submissions(
    subreddit: str,
    after_ts: int,
    before_ts: int,
    primary: str = "arctic_shift",
) -> tuple[list[dict], str]:
    """Try primary; fall back to the other source if it returns 0.

    Returns (posts, source_used).
    """
    if primary == "pullpush":
        first, fallback = _pullpush_paginate, _arctic_paginate
        first_name, fb_name = "pullpush", "arctic_shift"
    else:
        first, fallback = _arctic_paginate, _pullpush_paginate
        first_name, fb_name = "arctic_shift", "pullpush"
    posts = first(subreddit, after_ts, before_ts)
    if posts:
        return posts, first_name
    posts = fallback(subreddit, after_ts, before_ts)
    return posts, fb_name


def filter_top_percentile(posts: list[dict], top_pct: int, floor: int) -> list[dict]:
    if not posts:
        return []
    sorted_posts = sorted(posts, key=lambda p: p.get("score", 0) or 0, reverse=True)
    cutoff_idx = max(1, int(len(sorted_posts) * top_pct / 100))
    threshold_score = sorted_posts[cutoff_idx - 1].get("score", 0) or 0
    threshold = max(threshold_score, floor)
    return [p for p in sorted_posts if (p.get("score", 0) or 0) >= threshold]


def fetch_comments(post_id: str, primary: str = "arctic_shift") -> list[dict]:
    """Fetch up to 100 top comments for a post.

    arctic_shift caps `limit` at 100 (returns 400 above that). pullpush accepts
    larger sizes but its comments endpoint has been flaky. We accept 100 max as a
    reasonable cap — most posts have far fewer substantive comments above the
    score floor anyway.

    `post_id` may be raw ('1abc') or fullname ('t3_1abc').
    """
    raw_id = post_id.split("_", 1)[1] if post_id.startswith("t3_") else post_id
    fullname = post_id if post_id.startswith("t3_") else f"t3_{post_id}"

    sources: list[tuple[str, str, dict]] = [
        ("arctic_shift", ARCTIC_COMMENTS, {"link_id": fullname, "limit": 100}),
        ("pullpush", PULLPUSH_COMMENTS, {"link_id": raw_id, "size": 100}),
    ]
    if primary == "pullpush":
        sources.reverse()

    for name, endpoint, params in sources:
        try:
            data = _get(endpoint, params=params)
            hits = data.get("data") or []
            if hits:
                return hits
        except Exception as e:
            print(f"  [{name}] comments failed for {post_id}: {e}")
    return []


def scrape_reddit_historical(
    corpus_dir: Path,
    config_dir: Path,
    months_back: int = 12,
    dedup: DedupIndex | None = None,
    use_arctic_shift: bool = True,  # arctic_shift is now primary
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

    primary = "arctic_shift" if use_arctic_shift else "pullpush"
    now = datetime.now(timezone.utc)
    n_records = 0
    n_windows_with_posts = 0

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
            posts, source_used = search_submissions(sub, after_ts, before_ts, primary=primary)
            if posts:
                n_windows_with_posts += 1
            kept = filter_top_percentile(posts, top_pct, floor)
            print(
                f"  src={source_used} pulled={len(posts)} "
                f"kept_top_{top_pct}%_floor_{floor}={len(kept)}"
            )

            for p in kept:
                pid = str(p.get("id") or "")
                if not pid:
                    continue
                permalink_path = p.get("permalink") or ""
                permalink = (
                    f"https://www.reddit.com{permalink_path}"
                    if permalink_path
                    else f"https://www.reddit.com/r/{sub}/comments/{pid}/"
                )
                date_iso = utc_iso_from_unix(p.get("created_utc", 0))
                title = p.get("title") or ""
                selftext = p.get("selftext") or ""
                full_text = f"{title}\n\n{selftext}".strip()
                score = int(p.get("score", 0) or 0)

                if dedup and not dedup.should_write("reddit", permalink, score):
                    continue

                post_model = detect_model(full_text, keywords)
                write_record(
                    corpus_dir,
                    Record(
                        source="reddit",
                        source_subkey=f"r/{sub}",
                        post_id=pid,
                        permalink=permalink,
                        date=date_iso,
                        model_mentioned=post_model,
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
                comments = fetch_comments(pid, primary=primary)
                for c in comments:
                    cscore = int(c.get("score", 0) or 0)
                    if cscore < comment_floor:
                        continue
                    ctext = c.get("body") or ""
                    if not ctext or ctext in ("[deleted]", "[removed]"):
                        continue
                    cid = str(c.get("id") or "")
                    cperm_path = c.get("permalink") or ""
                    cpermalink = (
                        f"https://www.reddit.com{cperm_path}"
                        if cperm_path
                        else f"{permalink}{cid}/"
                    )
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
                            model_mentioned=detect_model(
                                ctext, keywords, parent_model=post_model
                            ),
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

    # Fail-loud guard: if no window across any subreddit returned posts,
    # arctic_shift is almost certainly down (or both arctic_shift AND
    # pullpush are). Without this, the cron silently produces a zero-Reddit
    # data.json that passes --strict (HN-only weeks still have records),
    # and the dashboard goes flat on Reddit without anyone noticing.
    expected_windows = len(subs) * months_back
    if expected_windows > 0 and n_windows_with_posts == 0:
        raise RuntimeError(
            f"reddit_hist: ALL {expected_windows} (sub × month) windows "
            f"returned 0 posts. arctic_shift / pullpush are likely down. "
            f"Failing the run rather than silently producing zero-Reddit data."
        )

    print(
        f"[reddit_hist] total records: {n_records} "
        f"(windows_with_posts={n_windows_with_posts}/{expected_windows})",
        flush=True,
    )
    return n_records

import hashlib
import html
import os
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, Dict, List
from urllib.parse import urlparse, urlunparse

import feedparser
import yaml
from dateutil import parser as dtparser

ROOT = os.path.dirname(os.path.dirname(__file__))
CFG_PATH = os.path.join(ROOT, "feeds.yaml")
OUT_PATH = os.path.join(ROOT, "feed.xml")

# --- Text cleanup helpers -----------------------------------------------------

CTRL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def strip_control_chars(s: str) -> str:
    if not s:
        return ""
    return CTRL_RE.sub("", s)


def strip_html(s: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    if not s:
        return ""
    s = TAG_RE.sub("", s)
    s = WS_RE.sub(" ", s).strip()
    return s


def truncate(s: str, limit: int = 240) -> str:
    if not s:
        return ""
    if len(s) <= limit:
        return s
    # cut at a word boundary
    cut = s[:limit].rsplit(" ", 1)[0].strip()
    return (cut or s[:limit]).strip() + "…"


def canonicalize_url(u: str) -> str:
    """Drop query params/fragments to reduce duplicates and noisy tracking."""
    try:
        p = urlparse(u)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        return u


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


# --- RSS aggregation helpers --------------------------------------------------

def stable_guid(entry: Dict[str, Any], link: str) -> str:
    # Prefer stable identifiers; fall back to link; then title+date.
    raw = (
        entry.get("id")
        or entry.get("guid")
        or link
        or f"{entry.get('title','')}|{entry.get('published','') or entry.get('updated','')}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_dt(entry: Dict[str, Any]) -> datetime:
    for k in ("published", "updated"):
        v = entry.get(k)
        if v:
            try:
                dt = dtparser.parse(v)
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    # If upstream provides nothing, use "now" so item isn't stuck in 1970
    return datetime.now(timezone.utc)


def load_cfg() -> Dict[str, Any]:
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_rss(cfg: Dict[str, Any], items: List[Dict[str, Any]]) -> str:
    title = cfg.get("title", "Aggregated Feed")
    desc = cfg.get("description", "Combined RSS feed.")
    now = datetime.now(timezone.utc)

    out: List[str] = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append('<rss version="2.0">')
    out.append("<channel>")
    out.append(f"<title>{esc(title)}</title>")
    out.append(f"<link>{esc(cfg.get('link', ''))}</link>" if cfg.get("link") else "")
    out.append(f"<description>{esc(desc)}</description>")
    out.append("<language>en</language>")
    out.append("<ttl>5</ttl>")
    out.append(f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>")

    for it in items:
        out.append("<item>")

        # Title shows source + headline (good for Slack scanning)
        out.append(f"<title>{esc(it['source'] + ' | ' + it['title'])}</title>")

        # Link drives Slack click-through
        out.append(f"<link>{esc(it['link'])}</link>")

        # GUID should be stable across rebuilds so Slack doesn't repost duplicates
        out.append(f"<guid isPermaLink=\"false\">{it['guid']}</guid>")

        out.append(f"<pubDate>{format_datetime(it['dt'])}</pubDate>")

        # Clean, short, plain-text description (no HTML junk)
        out.append(f"<description>{esc(it.get('summary',''))}</description>")

        out.append("</item>")

    out.append("</channel>")
    out.append("</rss>")

    # remove any empty lines we inserted (e.g., optional <link>)
    return "\n".join([line for line in out if line != ""])


def main():
    cfg = load_cfg()
    feeds = cfg.get("feeds", [])
    max_items = int(cfg.get("max_items", 80))

    seen = set()
    items: List[Dict[str, Any]] = []

    for f in feeds:
        name = f["name"]
        url = f["url"]

        parsed = feedparser.parse(url)

        for e in parsed.entries:
            link_raw = e.get("link", "") or ""
            link = canonicalize_url(link_raw)
            if not link:
                continue

            guid = stable_guid(e, link)
            if guid in seen:
                continue
            seen.add(guid)

            dt = parse_dt(e)

            title_raw = e.get("title", "(no title)") or "(no title)"
            title = truncate(strip_html(strip_control_chars(title_raw)), limit=180)

            raw_summary = e.get("summary", "") or e.get("description", "") or ""
            summary = truncate(strip_html(strip_control_chars(raw_summary)), limit=240)

            items.append(
                {
                    "guid": guid,
                    "dt": dt,
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "source": name,
                }
            )

    items.sort(key=lambda x: x["dt"], reverse=True)
    items = items[:max_items]

    rss = build_rss(cfg, items)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(rss)

    print(f"Wrote {OUT_PATH} with {len(items)} items")


if __name__ == "__main__":
    main()

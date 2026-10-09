"""
engine.py - the scraping engine for Reel Studio.

Wraps the api-anything Instagram operations (learned in the instagram-data-api
skill) and turns raw CLI JSON into clean row dicts for the UI.

Ops used (both tier 1 = plain HTTP, no browser per call):
  instagram getReel    code=<shortcode>   -> reel metrics + music
  instagram getProfile username=<handle>  -> followers / bio / posts
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import datetime

# --- locate the api-anything CLI (Windows npm installs a .cmd shim) ---------
BIN = shutil.which("api-anything") or "api-anything"
if os.name == "nt" and not BIN.lower().endswith((".cmd", ".exe", ".bat")):
    for _ext in (".cmd", ".exe", ".bat"):
        if os.path.exists(BIN + _ext):
            BIN += _ext
            break


class EngineError(RuntimeError):
    pass


def _call(site: str, op: str, timeout: int = 60, **args):
    cmd = [BIN, "call", site, op] + [f"{k}={v}" for k, v in args.items()]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "class": "timeout", "reason": f"no answer in {timeout}s"}
    try:
        return json.loads(p.stdout)
    except Exception:
        return {"ok": False, "class": "parse_error",
                "reason": (p.stdout or p.stderr or "")[:200]}


def _first(res: dict) -> dict:
    d = res.get("data")
    if isinstance(d, list):
        return d[0] if d else {}
    if isinstance(d, dict):
        if d.get("rows"):
            return dict(zip(d.get("columns", []), d["rows"][0]))
        return d
    return {}


def _num(s):
    if s is None:
        return None
    m = re.match(r"^([\d.]+)\s*([KMB])?$", str(s).strip().replace(",", ""), re.I)
    if not m:
        return None
    return int(float(m.group(1)) * {"K": 1e3, "M": 1e6, "B": 1e9}.get((m.group(2) or "").upper(), 1))


# --- URL parsing ------------------------------------------------------------
REEL_RE = re.compile(r"instagram\.com/(?:[^/]+/)?(?:reels?|p|tv)/([A-Za-z0-9_-]{5,})")
PROFILE_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]+)/?(?:\?|$)")
RESERVED = {"reels", "reel", "p", "tv", "explore", "accounts", "stories", "direct"}
PROFILE_META = re.compile(
    r"^(?P<followers>[\d,\.]+[KMB]?)\s+Followers,\s*(?P<following>[\d,\.]+[KMB]?)\s+Following,\s*"
    r"(?P<posts>[\d,\.]+[KMB]?)\s+Posts\s*-\s*(?P<full_name>.*?)\s*\(@(?P<username>[^\)]+)\)"
    r"(?:\s+on Instagram:\s*\"(?P<bio>.*)\")?",
    re.S,
)


def reel_code(x: str) -> str:
    x = x.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{5,}", x):
        return x
    m = REEL_RE.search(x)
    if not m:
        raise EngineError(f"not a reel URL/code: {x}")
    return m.group(1)


def profile_username(x: str) -> str:
    x = x.strip().lstrip("@")
    if "/" not in x:
        return x
    m = PROFILE_RE.search(x)
    if not m or m.group(1).lower() in RESERVED:
        raise EngineError(f"not a profile URL: {x}")
    return m.group(1)


# --- row builders -----------------------------------------------------------
REEL_COLUMNS = ["input", "shortcode", "url", "username", "full_name", "likes", "comments",
                "reposts", "views", "date", "duration", "location", "music_title",
                "music_artist", "music_type", "caption", "owner_followers",
                "owner_followers_display", "verified", "width", "height", "tier", "ok", "error"]

PROFILE_COLUMNS = ["input", "username", "full_name", "followers", "followers_display",
                   "following", "posts", "bio", "profile_pic", "tier", "ok", "error"]


def reel_row(item: str, timeout: int = 60) -> dict:
    row = {c: None for c in REEL_COLUMNS}
    row["input"] = item
    row["ok"] = False
    try:
        code = reel_code(item)
    except EngineError as e:
        row["error"] = str(e)
        return row
    row["shortcode"] = code
    res = _call("instagram", "getReel", timeout=timeout, code=code)
    row["tier"] = res.get("tier")
    if not res.get("ok"):
        row["error"] = f"{res.get('class', 'error')}: {res.get('reason', '')}".strip(": ")
        return row
    r = _first(res)
    row.update({
        "url": f"https://www.instagram.com/reel/{code}/",
        "username": r.get("username"),
        "likes": r.get("like_count"),
        "comments": r.get("comment_count"),
        "reposts": r.get("media_repost_count"),
        "views": r.get("views"),
        "duration": r.get("duration"),
        "location": r.get("location"),
        "caption": (r.get("caption") or "").strip() or None,
        "verified": r.get("verified"),
        "width": r.get("width"),
        "height": r.get("height"),
        "ok": True,
    })
    if r.get("taken_at"):
        row["date"] = datetime.datetime.fromtimestamp(
            int(r["taken_at"]), datetime.timezone.utc).strftime("%Y-%m-%d")
    if r.get("music_title"):
        row["music_title"], row["music_artist"], row["music_type"] = (
            r["music_title"], r.get("music_artist"), "licensed")
    elif r.get("audio_title"):
        row["music_title"], row["music_artist"], row["music_type"] = (
            r["audio_title"], r.get("audio_artist"), "original")
    return row


def profile_row(item: str, timeout: int = 60) -> dict:
    row = {c: None for c in PROFILE_COLUMNS}
    row["input"] = item
    row["ok"] = False
    try:
        username = profile_username(item)
    except EngineError as e:
        row["error"] = str(e)
        return row
    row["username"] = username
    res = _call("instagram", "getProfile", timeout=timeout, username=username)
    row["tier"] = res.get("tier")
    if not res.get("ok"):
        row["error"] = f"{res.get('class', 'error')}: {res.get('reason', '')}".strip(": ")
        return row
    r = _first(res)
    text = (r.get("desc") or r.get("meta") or "").strip()
    m = PROFILE_META.match(text)
    row["ok"] = True
    row["profile_pic"] = r.get("pic")
    if m:
        row.update({
            "followers": _num(m.group("followers")),
            "followers_display": m.group("followers"),
            "following": _num(m.group("following")),
            "posts": _num(m.group("posts")),
            "full_name": m.group("full_name").strip(),
            "bio": (m.group("bio") or "").strip().replace("\\n", " ") or None,
        })
    return row


def session_status() -> dict:
    """Quick check that the Instagram session still answers (tier 1)."""
    res = _call("instagram", "getProfile", timeout=30, username="nasa")
    return {"ok": bool(res.get("ok")), "tier": res.get("tier"),
            "class": res.get("class"), "reason": res.get("reason")}


# ---------------------------------------------------------------- fast mode
# Direct HTTP path (no node spawn, no 1 s spacing) so the runner can use a
# thread pool. Same row shape as the CLI path so the UI and exports do not care.
import fastfetch  # noqa: E402


def _reel_row_from(d: dict, code: str, item: str) -> dict:
    row = {c: None for c in REEL_COLUMNS}
    row.update({"input": item, "shortcode": d.get("code") or code, "ok": True, "tier": 1,
                "url": f"https://www.instagram.com/reel/{code}/",
                "username": d.get("username"), "likes": d.get("like_count"),
                "comments": d.get("comment_count"), "reposts": d.get("media_repost_count"),
                "views": d.get("views"), "duration": d.get("duration"),
                "location": d.get("location"), "caption": (d.get("caption") or "").strip() or None,
                "verified": d.get("verified"), "width": d.get("width"), "height": d.get("height")})
    if d.get("taken_at"):
        row["date"] = datetime.datetime.fromtimestamp(
            int(d["taken_at"]), datetime.timezone.utc).strftime("%Y-%m-%d")
    if d.get("music_title"):
        row["music_title"], row["music_artist"], row["music_type"] = (
            d["music_title"], d.get("music_artist"), "licensed")
    elif d.get("audio_title"):
        row["music_title"], row["music_artist"], row["music_type"] = (
            d["audio_title"], d.get("audio_artist"), "original")
    return row


def fast_reel_row(item: str, timeout: int = 25) -> dict:
    row = {c: None for c in REEL_COLUMNS}
    row["input"] = item
    row["ok"] = False
    try:
        code = reel_code(item)
    except EngineError as e:
        row["error"] = str(e)
        return row
    try:
        d = fastfetch.reel(code, timeout=timeout)
    except fastfetch.SessionMissing as e:
        row["error"] = f"no_session: {e}"
        row["shortcode"] = code
        return row
    except fastfetch.AuthWall as e:
        row["error"] = f"auth: {e}"
        row["shortcode"] = code
        return row
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
        row["shortcode"] = code
        return row
    return _reel_row_from(d, code, item)


def fast_profile_row(item: str, timeout: int = 25) -> dict:
    row = {c: None for c in PROFILE_COLUMNS}
    row["input"] = item
    row["ok"] = False
    try:
        username = profile_username(item)
    except EngineError as e:
        row["error"] = str(e)
        return row
    row["username"] = username
    try:
        d = fastfetch.profile(username, timeout=timeout)
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
        return row
    row.update({"ok": True, "tier": 1, "profile_pic": d.get("pic"),
                "followers": d.get("followers"), "followers_display": d.get("followers_display"),
                "following": d.get("following"), "posts": d.get("posts"),
                "full_name": d.get("full_name"), "bio": d.get("bio")})
    return row


def fast_session_status() -> dict:
    r = fastfetch.preflight()
    return {"ok": bool(r.get("ok")), "tier": 1, "mode": "fast",
            "class": r.get("class"), "reason": r.get("reason"), "ms": r.get("ms")}


def fast_available() -> bool:
    try:
        return fastfetch.preflight().get("ok", False)
    except Exception:
        return False

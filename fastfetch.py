"""
fastfetch.py - direct HTTP engine for Reel Studio.

Bypasses the `api-anything` CLI (no node spawn, no forced 1s spacing) by using
the exact request headers the learned spec recorded, plus the Instagram session
cookies api-anything already imported.

That makes the app parallelisable: a thread pool turns ~3.5 s/reel sequential
into ~0.7 s/reel effective at 5-8 workers.

The CLI stays available as "safe" mode and remains the source of truth for the
session; we only read its own files.
"""
from __future__ import annotations

import gzip
import html as _html
import http.client
import json
import os
import re
import ssl
import threading
import time

API_HOME = os.environ.get("API_ANYTHING_HOME") or os.path.join(os.path.expanduser("~"), ".api-anything")
SITE = "instagram"

MEDIA_RE = re.compile(r'"xdt_api__v1__media__shortcode__web_info":\{"items":\[(\{)')
PROFILE_META = re.compile(
    r"^(?P<followers>[\d,\.]+[KMB]?)\s+Followers,\s*(?P<following>[\d,\.]+[KMB]?)\s+Following,\s*"
    r"(?P<posts>[\d,\.]+[KMB]?)\s+Posts\s*-\s*(?P<full_name>.*?)\s*\(@(?P<username>[^\)]+)\)"
    r"(?:\s+on Instagram:\s*\"(?P<bio>.*)\")?",
    re.S,
)

_tls = threading.local()
_lock = threading.Lock()


class SessionMissing(RuntimeError):
    pass


class AuthWall(RuntimeError):
    pass


# --------------------------------------------------------------- session
def _spec_op(op_name: str) -> dict:
    path = os.path.join(API_HOME, "sites", f"{SITE}.json")
    spec = json.load(open(path, encoding="utf-8"))
    for op in spec.get("operations", []):
        if op.get("name") == op_name:
            return op
    raise SessionMissing(f"operation {op_name!r} not found in {path}")


def _cookie_header() -> str:
    path = os.path.join(API_HOME, "sessions", f"{SITE}.json")
    if not os.path.exists(path):
        raise SessionMissing("no instagram session; use Settings > Refresh session")
    sess = json.load(open(path, encoding="utf-8"))
    ck = sess.get("cookies") or []
    if not any(c.get("name") == "sessionid" for c in ck):
        raise SessionMissing("session has no sessionid; refresh it")
    return "; ".join(f"{c['name']}={c['value']}" for c in ck)


def _headers_for(op_name: str) -> dict:
    h = dict(_spec_op(op_name)["request"].get("headers") or {})
    h["cookie"] = _cookie_header()
    h["accept-encoding"] = "gzip, deflate"
    # drop hop-by-hop / length hints the origin set
    for k in ("content-length", "host", "connection"):
        h.pop(k, None)
    return h


# --------------------------------------------------------------- transport
def _conn():
    c = getattr(_tls, "conn", None)
    if c is None:
        ctx = ssl.create_default_context()
        c = http.client.HTTPSConnection("www.instagram.com", timeout=25, context=ctx)
        _tls.conn = c
    return c


def _drop_conn():
    c = getattr(_tls, "conn", None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass
        _tls.conn = None


def _get(url: str, headers: dict, timeout: int = 25, retry: bool = True) -> str:
    """GET with keep-alive. Returns decoded body text."""
    path = url.split("www.instagram.com", 1)[-1] or "/"
    try:
        c = _conn()
        c.timeout = timeout
        c.request("GET", path, headers=headers)
        r = c.getresponse()
        raw = r.read()
        enc = (r.getheader("Content-Encoding") or "").lower()
        status = r.status
        if r.will_close:
            _drop_conn()
    except Exception:
        _drop_conn()
        if not retry:
            raise
        return _get(url, headers, timeout, retry=False)
    if "gzip" in enc:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    elif "deflate" in enc:
        try:
            import zlib
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        except Exception:
            pass
    if status >= 400:
        raise RuntimeError(f"http {status}")
    return raw.decode("utf-8", "replace")


# --------------------------------------------------------------- extraction
def _pick(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _num(s):
    if s is None:
        return None
    m = re.match(r"^([\d.]+)\s*([KMB])?$", str(s).strip().replace(",", ""), re.I)
    if not m:
        return None
    return int(float(m.group(1)) * {"K": 1e3, "M": 1e6, "B": 1e9}.get((m.group(2) or "").upper(), 1))


def reel(code: str, timeout: int = 25) -> dict:
    """Fetch one reel page and return the picked media fields."""
    headers = _headers_for("getReel")
    body = _get(f"https://www.instagram.com/reels/{code}/", headers, timeout)
    m = MEDIA_RE.search(body)
    if not m:
        raise AuthWall("no media block in the response; session likely expired")
    try:
        media, _ = json.JSONDecoder().raw_decode(body, m.start(1))
    except ValueError as e:
        raise RuntimeError(f"could not parse the media block: {e}")
    cm = media.get("clips_metadata") or {}
    mi = (cm.get("music_info") or {}).get("music_asset_info") or {}
    os_ = cm.get("original_sound_info") or {}
    cap = media.get("caption") or {}
    out = {
        "code": media.get("code") or code,
        "id": media.get("id"),
        "pk": media.get("pk"),
        "taken_at": media.get("taken_at"),
        "media_type": media.get("media_type"),
        "product_type": media.get("product_type"),
        "like_count": media.get("like_count"),
        "comment_count": media.get("comment_count"),
        "media_repost_count": media.get("media_repost_count"),
        "views": media.get("view_count"),
        "username": _pick(media, "user.username"),
        "verified": _pick(media, "user.is_verified"),
        "location": _pick(media, "location.name"),
        "caption": cap.get("text"),
        "width": media.get("original_width"),
        "height": media.get("original_height"),
        "duration": media.get("video_duration"),
        "music_title": mi.get("title"),
        "music_artist": mi.get("display_artist"),
        "audio_title": os_.get("original_audio_title"),
        "audio_artist": _pick(os_, "ig_artist.username"),
        "audio_asset_id": os_.get("audio_asset_id"),
    }
    return out


def profile(username: str, timeout: int = 25) -> dict:
    headers = _headers_for("getProfile")
    body = _get(f"https://www.instagram.com/{username}/", headers, timeout)
    if MEDIA_RE.search(body) is None and '"xdt_api' not in body:
        # profile pages carry meta tags; a login wall does not
        if 'property="og:description"' not in body and 'name="description"' not in body:
            raise AuthWall("profile page came back without metadata; session likely expired")
    def meta(prop):
        m = re.search(r'<meta[^>]*(?:property|name)="' + re.escape(prop) + r'"[^>]*content="([^"]*)"', body)
        if not m:
            m = re.search(r'<meta[^>]*content="([^"]*)"[^>]*(?:property|name)="' + re.escape(prop) + r'"', body)
        return m.group(1) if m else None
    desc = _html.unescape(meta("description") or meta("og:description") or "")
    out = {"username": username, "pic": meta("og:image"),
           "followers": None, "followers_display": None, "following": None,
           "posts": None, "full_name": None, "bio": None, "raw_text": desc}
    mm = PROFILE_META.match(desc.strip())
    if mm:
        out.update({
            "followers": _num(mm.group("followers")),
            "followers_display": mm.group("followers"),
            "following": _num(mm.group("following")),
            "posts": _num(mm.group("posts")),
            "full_name": mm.group("full_name").strip(),
            "bio": (mm.group("bio") or "").strip().replace("\\n", " ") or None,
        })
    else:
        # looser fallback: at least get the follower count out
        f = re.search(r"([\d,\.]+[KMB]?)\s+Followers", desc)
        if f:
            out["followers"] = _num(f.group(1))
            out["followers_display"] = f.group(1)
        g = re.search(r"([\d,\.]+[KMB]?)\s+Following", desc)
        if g:
            out["following"] = _num(g.group(1))
        p = re.search(r"([\d,\.]+[KMB]?)\s+Posts", desc)
        if p:
            out["posts"] = _num(p.group(1))
        nm = re.match(r"^.*?Posts\s*-\s*(.+?)\s*\(@", desc)
        if nm:
            out["full_name"] = nm.group(1).strip()
    return out


def preflight() -> dict:
    """Cheap session check with no CLI: fetch one known reel."""
    t0 = time.time()
    try:
        r = reel("Dd6Pu8KpFJc", timeout=20)
        return {"ok": bool(r.get("like_count") is not None or r.get("username")),
                "ms": int((time.time() - t0) * 1000), "user": r.get("username")}
    except SessionMissing as e:
        return {"ok": False, "class": "no_session", "reason": str(e)}
    except AuthWall as e:
        return {"ok": False, "class": "auth", "reason": str(e)}
    except Exception as e:
        return {"ok": False, "class": "error", "reason": f"{type(e).__name__}: {e}"}

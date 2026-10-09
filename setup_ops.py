#!/usr/bin/env python3
"""
setup_ops.py - one time installer for the Instagram operations Reel Studio drives.

Reel Studio does not scrape by itself. It calls two operations learned by
`api-anything`:

    instagram getReel     reel data: likes, comments, reposts, caption,
                          owner, location, duration, music title + artist
    instagram getProfile  profile data: followers, following, posts, bio, picture

This script learns both. Run it once, after installing api-anything and signing
in to Instagram.

    python setup_ops.py             learn both operations
    python setup_ops.py --verify    only check what is already there
    python setup_ops.py --force     re-learn even if they already exist

Requirements: Node 22.13+, api-anything installed globally, Google Chrome,
and an Instagram session (the script tells you how to create one if missing).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

API_HOME = os.environ.get("API_ANYTHING_HOME") or os.path.join(os.path.expanduser("~"), ".api-anything")
SITE = "instagram"
SITE_FILE = os.path.join(API_HOME, "sites", f"{SITE}.json")
SESSION_FILE = os.path.join(API_HOME, "sessions", f"{SITE}.json")


# ------------------------------------------------------------------ helpers
def resolve_bin() -> str:
    """Windows installs a .cmd shim; node spawns fail without the extension."""
    b = shutil.which("api-anything") or "api-anything"
    if os.name == "nt" and not b.lower().endswith((".cmd", ".exe", ".bat")):
        for ext in (".cmd", ".exe", ".bat"):
            if os.path.exists(b + ext):
                return b + ext
    return b


BIN = resolve_bin()


def run(args: list[str], timeout: int = 300) -> tuple[int, str]:
    p = subprocess.run([BIN] + args, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def ok(msg): print(f"  ok    {msg}")
def bad(msg): print(f"  FAIL  {msg}")
def info(msg): print(f"  ..    {msg}")


def have_session() -> bool:
    if not os.path.exists(SESSION_FILE):
        return False
    try:
        s = json.load(open(SESSION_FILE, encoding="utf-8"))
    except Exception:
        return False
    return any(c.get("name") == "sessionid" for c in (s.get("cookies") or []))


def learned_ops() -> set[str]:
    if not os.path.exists(SITE_FILE):
        return set()
    try:
        d = json.load(open(SITE_FILE, encoding="utf-8"))
        return {o.get("name") for o in d.get("operations", [])}
    except Exception:
        return set()


# ------------------------------------------------------------------ recipes
# The reel page server renders the media object; anchor on its key so the
# recipe survives Instagram reordering the surrounding payload.
REEL_EMBEDDED = r'"xdt_api__v1__media__shortcode__web_info":\{"items":\[(\{)'
REEL_PICK = (
    "code,id,pk,taken_at,media_type,product_type,like_count,comment_count,"
    "media_repost_count,views=view_count,username=user.username,verified=user.is_verified,"
    "location=location.name,caption=caption.text,width=original_width,height=original_height,"
    "duration=video_duration,"
    "music_title=clips_metadata.music_info.music_asset_info.title,"
    "music_artist=clips_metadata.music_info.music_asset_info.display_artist,"
    "audio_title=clips_metadata.original_sound_info.original_audio_title,"
    "audio_artist=clips_metadata.original_sound_info.ig_artist.username,"
    "audio_asset_id=clips_metadata.original_sound_info.audio_asset_id"
)
PROFILE_HTML = json.dumps({
    "items": "head",
    "fields": {
        "title": 'meta[property="og:title"]@content',
        "meta": 'meta[property="og:description"]@content',
        "desc": 'meta[name="description"]@content',
        "pic": 'meta[property="og:image"]@content',
        "canonical": 'meta[property="og:url"]@content',
    },
})

REEL_CMD = [
    "add", SITE, "getReel",
    "--trigger", "https://www.instagram.com/reels/{code}/",
    "--example", "code=Dd6Pu8KpFJc",
    "--embedded", REEL_EMBEDDED,
    "--pick", REEL_PICK,
    "--description",
    "Instagram reel data by shortcode: likes, comments, reposts, caption, owner, "
    "location, duration, music title and artist",
]
PROFILE_CMD = [
    "add", SITE, "getProfile",
    "--trigger", "https://www.instagram.com/{username}/",
    "--example", "username=theakshattongia",
    "--html", PROFILE_HTML,
    "--description",
    "Instagram profile data by username: name, followers, following, posts, bio, picture",
]


# ------------------------------------------------------------------ main
def main() -> int:
    force = "--force" in sys.argv
    verify_only = "--verify" in sys.argv

    print("\nReel Studio :: operation setup\n" + "-" * 34)

    code, out = run(["--help"], timeout=60)
    if code != 0 and "api-anything" not in out:
        bad("api-anything is not on PATH")
        print("\n  Install it first:")
        print("    git clone --depth 1 https://github.com/goodnight000/api-anything.git")
        print('    cd api-anything && npm ci && npm install -g "$(npm pack --silent)"')
        print("  Then run this script again.\n")
        return 1
    ok("api-anything found")

    if not have_session():
        bad("no Instagram session in api-anything")
        print("\n  Create one (a Chrome window opens, sign in, then close it):")
        print(f"    {os.path.basename(BIN)} login {SITE} --window")
        print("  Then run this script again.\n")
        return 1
    ok("Instagram session present")

    existing = learned_ops()
    if verify_only:
        for name in ("getReel", "getProfile"):
            (ok if name in existing else bad)(f"operation {name}")
        return 0 if {"getReel", "getProfile"} <= existing else 1

    for name, cmd in (("getReel", REEL_CMD), ("getProfile", PROFILE_CMD)):
        if name in existing and not force:
            ok(f"{name} already learned, skipping")
            continue
        info(f"learning {name} (runs Chrome twice, give it a moment)")
        try:
            code, out = run(cmd)
        except subprocess.TimeoutExpired:
            bad(f"{name} timed out")
            return 1
        if code != 0 or '"ok":true' not in out.replace(" ", ""):
            bad(f"{name} failed")
            print("   " + out.strip()[:500])
            return 1
        ok(f"{name} learned")

    print("\nverifying with live calls\n" + "-" * 34)
    fails = 0
    for label, args in (
        ("getReel", ["call", SITE, "getReel", "code=Dd6Pu8KpFJc"]),
        ("getProfile", ["call", SITE, "getProfile", "username=nasa"]),
    ):
        try:
            code, out = run(args, timeout=120)
        except subprocess.TimeoutExpired:
            bad(f"{label} timed out")
            fails += 1
            continue
        try:
            d = json.loads(out.strip().splitlines()[0])
        except Exception:
            bad(f"{label} returned something unreadable")
            fails += 1
            continue
        if d.get("ok"):
            data = d.get("data")
            row = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else {}
            snippet = {k: row.get(k) for k in ("username", "like_count", "followers_display") if row.get(k) is not None}
            ok(f"{label} answered, tier {d.get('tier')}  {snippet}")
        else:
            bad(f"{label}: {d.get('class')} - {d.get('reason')}")
            fails += 1

    print("-" * 34)
    if fails:
        print("Setup finished with problems. Fix the failures above, then re-run.\n")
        return 1
    print("Setup complete. Start the app from the Reel Studio shortcut, or:\n")
    print("    python server.py\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

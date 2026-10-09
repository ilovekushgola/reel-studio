"""
server.py - Reel Studio backend. Python stdlib only, no dependencies.

Serves the single-page UI and runs scraping jobs on a background thread.

  GET  /                          -> static/index.html
  GET  /static/<file>             -> css / js
  GET  /api/status                -> Instagram session check
  GET  /api/settings              -> saved defaults
  POST /api/settings              -> save defaults
  POST /api/jobs                  -> {type, items[], settings{}} -> {id}
  GET  /api/jobs                  -> job summaries
  GET  /api/jobs/<id>             -> full job (results, log, progress)
  POST /api/jobs/<id>/stop        -> request stop
  DELETE /api/jobs/<id>           -> delete a job
  GET  /api/jobs/<id>/export?fmt=csv|xlsx|json
  POST /api/session/refresh       -> opens the api-anything login window
  POST /api/shutdown              -> stop the server

Run:  python server.py           (opens http://127.0.0.1:8787)
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import engine
from xlsx_writer import write_xlsx

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
JOBS_DIR = os.path.join(HERE, "jobs")
EXPORT_DIR = os.path.join(HERE, "exports")
SETTINGS_FILE = os.path.join(HERE, "settings.json")
PORT = int(os.environ.get("REEL_STUDIO_PORT", "8787"))

os.makedirs(JOBS_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

DEFAULT_SETTINGS = {"delay_ms": 1000, "retries": 1, "timeout_s": 60, "enrich": True,
                    "mode": "fast", "workers": 6}
LOCK = threading.Lock()
JOBS: dict[str, dict] = {}
PROFILE_CACHE: dict[str, dict] = {}


# ----------------------------- helpers --------------------------------------
def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s = json.load(f)
        return {**DEFAULT_SETTINGS, **s}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(s: dict) -> dict:
    merged = {**DEFAULT_SETTINGS, **{k: s[k] for k in DEFAULT_SETTINGS if k in s}}
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    return merged


def log(job: dict, msg: str, level: str = "info"):
    job["log"].append({"t": time.strftime("%H:%M:%S"), "level": level, "msg": msg})
    if len(job["log"]) > 500:
        del job["log"][:-400]


def persist(job: dict):
    try:
        with open(os.path.join(JOBS_DIR, f"{job['id']}.json"), "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False)
    except Exception:
        pass


def public_job(job: dict) -> dict:
    return {k: v for k, v in job.items() if k != "_thread"}


def columns_for(kind: str) -> list[str]:
    return engine.REEL_COLUMNS if kind == "reels" else engine.PROFILE_COLUMNS


# ----------------------------- job runner -----------------------------------
def _profile_cached(username: str, timeout: int) -> dict:
    if username in PROFILE_CACHE:
        return PROFILE_CACHE[username]
    row = engine.profile_row(username, timeout=timeout)
    PROFILE_CACHE[username] = row
    return row


def run_job(job: dict):
    s = job["settings"]
    delay = max(0, int(s.get("delay_ms", 1000))) / 1000.0
    retries = max(0, int(s.get("retries", 1)))
    timeout = max(10, int(s.get("timeout_s", 60)))
    enrich = bool(s.get("enrich", True))
    kind = job["type"]

    with LOCK:
        job["status"] = "running"
        job["started_at"] = time.time()
    log(job, f"started {kind} job: {job['total']} item(s), delay {int(delay*1000)}ms, "
             f"retries {retries}, timeout {timeout}s, enrich={enrich}")

    for idx, item in enumerate(job["items"]):
        if job.get("stop"):
            log(job, "stopped by user", "warn")
            break
        job["current"] = item
        row = None
        for attempt in range(retries + 1):
            try:
                row = (engine.reel_row if kind == "reels" else engine.profile_row)(item, timeout=timeout)
            except Exception as e:  # noqa
                row = {"input": item, "ok": False, "error": str(e)}
            if row.get("ok") or attempt >= retries:
                break
            log(job, f"retry {attempt+1}/{retries} for {item} ({row.get('error')})", "warn")
            time.sleep(min(3.0, delay + 1))
        job["results"].append(row)
        job["done"] = len(job["results"])
        if row and row.get("ok"):
            job["ok_count"] += 1
            if kind == "reels":
                log(job, f"[{job['done']}/{job['total']}] @{row.get('username')} "
                         f"likes={row.get('likes')} comments={row.get('comments')} "
                         f"music={row.get('music_title')}")
            else:
                log(job, f"[{job['done']}/{job['total']}] @{row.get('username')} "
                         f"followers={row.get('followers_display')}")
        else:
            job["fail_count"] += 1
            log(job, f"[{job['done']}/{job['total']}] FAILED {item} - {row.get('error')}", "error")
        if idx < job["total"] - 1 and not job.get("stop"):
            time.sleep(delay)
        if job["done"] % 5 == 0:
            persist(job)

    # profile enrichment for reels
    if kind == "reels" and enrich and not job.get("stop"):
        handles = []
        for r in job["results"]:
            u = r.get("username")
            if r.get("ok") and u and u not in handles:
                handles.append(u)
        if handles:
            log(job, f"enriching {len(handles)} unique profile(s) with follower counts")
            job["enrich_done"] = 0
            job["enrich_total"] = len(handles)
            for h in handles:
                if job.get("stop"):
                    break
                p = _profile_cached(h, timeout)
                job["enrich_done"] += 1
                for r in job["results"]:
                    if r.get("username") == h:
                        r["owner_followers"] = p.get("followers")
                        r["owner_followers_display"] = p.get("followers_display")
                log(job, f"  profile {job['enrich_done']}/{job['enrich_total']} @{h} "
                         f"-> {p.get('followers_display')}")
                time.sleep(delay)
            persist(job)

    with LOCK:
        job["status"] = "stopped" if job.get("stop") else "done"
        job["finished_at"] = time.time()
        job["current"] = None
    log(job, f"finished: {job['ok_count']} ok, {job['fail_count']} failed, "
             f"{job['done']}/{job['total']}")
    persist(job)


# ----------------------------- fast job runner -------------------------------
def run_job_fast(job: dict):
    """Parallel runner: direct HTTP via fastfetch, thread pool, no forced 1 s gap."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    s = job["settings"]
    workers = max(1, min(12, int(s.get("workers", 6))))
    retries = max(0, int(s.get("retries", 1)))
    timeout = max(10, int(s.get("timeout_s", 60)))
    enrich = bool(s.get("enrich", True))
    kind = job["type"]
    rowfn = engine.fast_reel_row if kind == "reels" else engine.fast_profile_row

    with LOCK:
        job["status"] = "running"
        job["started_at"] = time.time()
    log(job, f"started {kind} job in fast mode: {job['total']} item(s), {workers} workers, "
             f"retries {retries}, timeout {timeout}s, enrich={enrich}")

    auth_fail = 0

    def work(item):
        row = None
        for attempt in range(retries + 1):
            try:
                row = rowfn(item, timeout=timeout)
            except Exception as e:
                row = {"input": item, "ok": False, "error": f"{type(e).__name__}: {e}"}
            if row.get("ok") or attempt >= retries:
                return row
            time.sleep(0.8 * (attempt + 1))
        return row

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, it): it for it in job["items"]}
        for fut in as_completed(futs):
            if job.get("stop"):
                for f in futs:
                    f.cancel()
                log(job, "stopped by user", "warn")
                break
            item = futs[fut]
            row = fut.result()
            job["results"].append(row)
            job["done"] = len(job["results"])
            job["current"] = item
            if row and row.get("ok"):
                job["ok_count"] += 1
                if kind == "reels":
                    log(job, f"[{job['done']}/{job['total']}] @{row.get('username')} "
                             f"likes={row.get('likes')} comments={row.get('comments')} "
                             f"music={row.get('music_title')}")
                else:
                    log(job, f"[{job['done']}/{job['total']}] @{row.get('username')} "
                             f"followers={row.get('followers_display')}")
            else:
                job["fail_count"] += 1
                err = str(row.get("error") or "")
                if err.startswith("auth") or err.startswith("no_session"):
                    auth_fail += 1
                log(job, f"[{job['done']}/{job['total']}] FAILED {item} - {err}", "error")
            if job["done"] % 5 == 0:
                persist(job)
            if auth_fail >= 3 and job["done"] <= 6:
                job["stop"] = True
                log(job, "three auth failures early: the Instagram session looks expired", "error")
                log(job, "open Settings and use Refresh session, then run again", "error")

    if kind == "reels" and enrich and not job.get("stop"):
        handles = []
        for r in job["results"]:
            u = r.get("username")
            if r.get("ok") and u and u not in handles:
                handles.append(u)
        if handles:
            job["enrich_total"] = len(handles)
            log(job, f"enriching {len(handles)} unique profile(s), {workers} workers")
            pool = ThreadPoolExecutor(max_workers=workers)
            try:
                futs = {pool.submit(engine.fast_profile_row, h, timeout): h for h in handles}
                for fut in as_completed(futs):
                    if job.get("stop"):
                        break
                    h = futs[fut]
                    try:
                        p = fut.result()
                    except Exception as e:
                        p = {"error": f"{type(e).__name__}: {e}"}
                    job["enrich_done"] = job.get("enrich_done", 0) + 1
                    for r in job["results"]:
                        if r.get("username") == h:
                            r["owner_followers"] = p.get("followers")
                            r["owner_followers_display"] = p.get("followers_display")
                    log(job, f"  profile {job['enrich_done']}/{job['enrich_total']} @{h} "
                             f"-> {p.get('followers_display') or p.get('error')}")
            finally:
                pool.shutdown(wait=False)
            persist(job)

    with LOCK:
        job["status"] = "stopped" if job.get("stop") else "done"
        job["finished_at"] = time.time()
        job["current"] = None
    took = job["finished_at"] - (job["started_at"] or job["finished_at"])
    log(job, f"finished in {took:.1f}s: {job['ok_count']} ok, {job['fail_count']} failed, "
             f"{job['done']}/{job['total']}")
    persist(job)


# ----------------------------- HTTP -----------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ReelStudio/1.0"

    def log_message(self, *a):  # keep console quiet
        pass

    # --- plumbing
    def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _file(self, path: str, ctype: str):
        try:
            with open(path, "rb") as f:
                self._send(200, f.read(), ctype)
        except FileNotFoundError:
            self._send(404, b"not found", "text/plain")

    # --- routes
    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)

        if p in ("/", "/index.html"):
            return self._file(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")
        if p.startswith("/static/"):
            name = os.path.basename(p)
            ctype = ("text/css" if name.endswith(".css") else
                     "application/javascript" if name.endswith(".js") else "text/plain")
            return self._file(os.path.join(STATIC, name), ctype + "; charset=utf-8")
        if p == "/api/settings":
            return self._json(load_settings())
        if p == "/api/status":
            return self._json(engine.session_status())
        if p == "/api/jobs":
            with LOCK:
                rows = [{"id": j["id"], "type": j["type"], "status": j["status"],
                         "total": j["total"], "done": j["done"], "ok": j["ok_count"],
                         "failed": j["fail_count"], "created_at": j["created_at"]}
                        for j in sorted(JOBS.values(), key=lambda x: x["created_at"], reverse=True)]
            return self._json(rows)
        if p.startswith("/api/jobs/"):
            rest = p[len("/api/jobs/"):]
            parts = rest.split("/")
            jid = parts[0]
            if len(parts) == 1:
                job = JOBS.get(jid)
                if not job:
                    return self._json({"error": "no such job"}, 404)
                with LOCK:
                    return self._json(public_job(job))
            if len(parts) == 2 and parts[1] == "export":
                return self._export(jid, (q.get("fmt") or ["csv"])[0])
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/settings":
            return self._json(save_settings(self._read_json()))
        if p == "/api/session/refresh":
            cmd = [engine.BIN, "login", "instagram", "--window"]
            try:
                subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
                return self._json({"ok": True, "msg": "Login window opened. Sign in, then close it."})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)
        if p == "/api/shutdown":
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return self._json({"ok": True})
        if p == "/api/jobs":
            body = self._read_json()
            kind = body.get("type", "reels")
            if kind not in ("reels", "profiles"):
                return self._json({"error": "type must be reels|profiles"}, 400)
            items = [str(x).strip() for x in (body.get("items") or []) if str(x).strip()]
            if not items:
                return self._json({"error": "no items"}, 400)
            s = save_settings({**load_settings(), **(body.get("settings") or {})})
            job = {"id": uuid.uuid4().hex[:10], "type": kind, "status": "queued",
                   "created_at": time.time(), "started_at": None, "finished_at": None,
                   "settings": s, "items": items, "total": len(items), "done": 0,
                   "ok_count": 0, "fail_count": 0, "current": None, "stop": False,
                   "results": [], "log": [], "enrich_done": 0, "enrich_total": 0}
            with LOCK:
                JOBS[job["id"]] = job
            log(job, f"queued {kind} job with {len(items)} item(s)")
            persist(job)
            target = run_job_fast if s.get("mode") == "fast" else run_job
            threading.Thread(target=target, args=(job,), daemon=True).start()
            return self._json({"id": job["id"], "total": len(items)})

        if p.startswith("/api/jobs/") and p.endswith("/stop"):
            jid = p[len("/api/jobs/"):-len("/stop")]
            job = JOBS.get(jid)
            if not job:
                return self._json({"error": "no such job"}, 404)
            job["stop"] = True
            log(job, "stop requested", "warn")
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        p = urlparse(self.path).path
        if p.startswith("/api/jobs/"):
            jid = p[len("/api/jobs/"):]
            with LOCK:
                JOBS.pop(jid, None)
            try:
                os.remove(os.path.join(JOBS_DIR, f"{jid}.json"))
            except OSError:
                pass
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)

    # --- export
    def _export(self, jid: str, fmt: str):
        job = JOBS.get(jid)
        if not job:
            return self._json({"error": "no such job"}, 404)
        cols = columns_for(job["type"])
        rows = [[r.get(c) for c in cols] for r in job["results"]]
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = f"{job['type']}_{stamp}"
        if fmt == "json":
            body = json.dumps(job["results"], ensure_ascii=False, indent=2).encode("utf-8")
            return self._send(200, body, "application/json",
                              {"Content-Disposition": f'attachment; filename="{base}.json"'})
        if fmt == "xlsx":
            path = os.path.join(EXPORT_DIR, base + ".xlsx")
            write_xlsx(path, cols, rows, sheet_name="Reels" if job["type"] == "reels" else "Profiles")
            with open(path, "rb") as f:
                data = f.read()
            return self._send(200, data,
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              {"Content-Disposition": f'attachment; filename="{base}.xlsx"'})
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        w.writerows(rows)
        return self._send(200, buf.getvalue().encode("utf-8-sig"), "text/csv",
                          {"Content-Disposition": f'attachment; filename="{base}.csv"'})


def main():
    # load previous jobs from disk so history survives restarts
    for fn in os.listdir(JOBS_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(JOBS_DIR, fn), encoding="utf-8") as f:
                    j = json.load(f)
                j["stop"] = True  # never auto-resume a disk job
                JOBS[j["id"]] = j
            except Exception:
                pass
    url = f"http://127.0.0.1:{PORT}"
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Reel Studio running at {url}   (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

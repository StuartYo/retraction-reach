"""Data sources: Retraction Watch (CSV, CC0), Crossref works (references), Semantic Scholar (citation intents).

Everything is cached on disk under data/cache so a rebuild does not hit the network again.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
RW_CSV = ROOT / "data" / "raw" / "retraction_watch.csv"
RW_URL = "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv"

UA = "relate-retraction/0.1 (research-integrity hackathon project)"
_mailto = os.environ.get("CROSSREF_MAILTO")
if _mailto:
    UA += f" mailto:{_mailto}"
HEADERS = {"User-Agent": UA}


def norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    for p in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "https://dx.doi.org/", "doi:"):
        if d.startswith(p):
            d = d[len(p):]
    d = d.strip().rstrip(".")
    return d if d.startswith("10.") and "/" in d else None


# ---------------------------------------------------------------- Retraction Watch
def _rw_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s.split(" ")[0], "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def download_rw(force: bool = False) -> Path:
    if RW_CSV.exists() and not force:
        return RW_CSV
    RW_CSV.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(RW_URL, headers=HEADERS, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(RW_CSV, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return RW_CSV


def load_retractions() -> dict[str, dict]:
    """DOI -> retraction record. Only RetractionNature == 'Retraction' (not corrections or concerns).
    If a paper has several retraction records, the earliest retraction date wins."""
    path = download_rw()
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    out: dict[str, dict] = {}
    for row in csv.DictReader(text.splitlines()):
        if row.get("RetractionNature") != "Retraction":
            continue
        doi = norm_doi(row.get("OriginalPaperDOI"))
        if not doi:
            continue
        rec = {
            "doi": doi,
            "record_id": row.get("Record ID", "").strip(),
            "title": (row.get("Title") or "").strip(),
            "journal": (row.get("Journal") or "").strip(),
            "date": _rw_date(row.get("RetractionDate")),
            "original_date": _rw_date(row.get("OriginalPaperDate")),
            "notice_doi": norm_doi(row.get("RetractionDOI")),
            "reasons": [x.strip().lstrip("+") for x in (row.get("Reason") or "").split(";") if x.strip()],
        }
        prev = out.get(doi)
        if prev is None or (rec["date"] and (not prev["date"] or rec["date"] < prev["date"])):
            out[doi] = rec
    return out


# ---------------------------------------------------------------- Crossref
_CR_FIELDS = "DOI,title,reference,published,issued,container-title,type,references-count"
_last_call = [0.0]


def _cr_cache_path(doi: str) -> Path:
    h = hashlib.sha1(doi.encode()).hexdigest()
    return CACHE / "crossref" / h[:2] / f"{h}.json"


def _date_parts(m: dict) -> str | None:
    for key in ("published", "issued"):
        dp = (m.get(key) or {}).get("date-parts") or [[None]]
        parts = [p for p in dp[0] if p]
        if parts:
            y = parts[0]
            mo = parts[1] if len(parts) > 1 else 1
            d = parts[2] if len(parts) > 2 else 1
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


def _compact(m: dict) -> dict:
    refs = m.get("reference") or []
    return {
        "doi": norm_doi(m.get("DOI")),
        "title": ((m.get("title") or [""])[0] or "")[:300],
        "journal": ((m.get("container-title") or [""])[0] or "")[:200],
        "date": _date_parts(m),
        "references_count": m.get("references-count", len(refs)),
        "refs": sorted({d for d in (norm_doi(r.get("DOI")) for r in refs) if d}),
    }


def _cr_get(params: dict) -> dict:
    for attempt in range(6):
        wait = 0.25 - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
        try:
            r = requests.get("https://api.crossref.org/works", params=params, headers=HEADERS, timeout=120)
            if r.status_code == 200:
                return r.json()["message"]
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep(2 ** attempt)
    raise RuntimeError("Crossref request kept failing")


def crossref_works(dois: list[str], batch: int = 80, progress=None) -> dict[str, dict]:
    """Fetch Crossref metadata (incl. reference DOIs) for many DOIs; cached per DOI.
    DOIs Crossref does not know are cached as {'doi': d, 'missing': True}."""
    out: dict[str, dict] = {}
    todo = []
    for d in dict.fromkeys(dois):
        p = _cr_cache_path(d)
        if p.exists():
            out[d] = json.loads(p.read_text(encoding="utf-8"))
        else:
            todo.append(d)
    for i in range(0, len(todo), batch):
        chunk = todo[i : i + batch]
        # DOIs containing commas break the filter syntax; fetch those one by one
        safe = [d for d in chunk if "," not in d]
        msg = _cr_get({"filter": ",".join("doi:" + d for d in safe), "rows": len(safe), "select": _CR_FIELDS}) if safe else {"items": []}
        got = {}
        for it in msg.get("items", []):
            c = _compact(it)
            if c["doi"]:
                got[c["doi"]] = c
        for d in chunk:
            rec = got.get(d) or {"doi": d, "missing": True, "refs": []}
            p = _cr_cache_path(d)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            out[d] = rec
        if progress:
            progress(min(i + batch, len(todo)), len(todo))
    return out


# ---------------------------------------------------------------- Semantic Scholar intents
_s2_last = [0.0]


def s2_reference_intents(citing_doi: str) -> dict[str, dict]:
    """cited DOI -> {intents, influential, context} for every reference of citing_doi that S2 knows.
    Uses the unauthenticated S2 Graph API (shared rate limit), cached forever."""
    h = hashlib.sha1(citing_doi.encode()).hexdigest()
    p = CACHE / "s2" / h[:2] / f"{h}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{citing_doi}/references"
    params = {"fields": "intents,isInfluential,contexts,externalIds", "limit": 1000}
    data = None
    for attempt in range(7):
        wait = 1.1 - (time.time() - _s2_last[0])
        if wait > 0:
            time.sleep(wait)
        _s2_last[0] = time.time()
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=60)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            data = r.json().get("data") or []
            break
        if r.status_code == 404:
            data = []
            break
        time.sleep(min(30, 2 ** attempt))
    if data is None:
        return {}  # do not cache failures
    out: dict[str, dict] = {}
    for item in data:
        cp = item.get("citedPaper") or {}
        d = norm_doi((cp.get("externalIds") or {}).get("DOI"))
        if not d:
            continue
        ctx = [c for c in (item.get("contexts") or []) if c]
        out[d] = {
            "intents": sorted(set(item.get("intents") or [])),
            "influential": bool(item.get("isInfluential")),
            "context": (ctx[0][:400] if ctx else None),
        }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out

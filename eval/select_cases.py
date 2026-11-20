"""Pick the evaluation cases once and freeze them in eval/cases.json.

Each case is the reference list of a real published paper (Crossref).
Stratum A: a Crossref random sample of journal articles (2019-2024).
Stratum B: papers (2019-2024) that cite one of ten well-known retracted papers, first one S2 returns.
Selection does not look at any result: the first papers that pass the size filter are taken, in the order
the APIs return them. 8 + 8 go to the evaluation set, 2 + 2 to a holdout set that is run once, later.
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from relate_retraction import sources  # noqa: E402

OUT = Path(__file__).resolve().parent / "cases.json"
FAMOUS = [
    "10.1016/s0140-6736(97)11096-0",   # Wakefield 1998, Lancet
    "10.1016/s0140-6736(20)31180-6",   # Surgisphere hydroxychloroquine, Lancet 2020
    "10.1056/nejmoa2007621",           # Surgisphere cardiovascular, NEJM 2020
    "10.1016/j.ijantimicag.2020.105949",  # Gautret hydroxychloroquine 2020
    "10.1038/nature12968",             # STAP cells 2014
    "10.1056/nejmoa1200303",           # PREDIMED 2013
    "10.1126/science.1256151",         # LaCour canvassing 2014
    "10.1038/nm1491",                  # Potti chemotherapy signatures 2006
    "10.1038/s41586-020-2012-7",       # control: NOT retracted (Zhou 2020, bat CoV); kept out if not in RW
    "10.1001/jama.2020.6019",          # placeholder, dropped if not retracted
]


def ok_size(doi):
    w = sources.crossref_works([doi])[doi]
    n = len(w.get("refs", []))
    return (20 <= n <= 80), n, w


def stratum_a(k=10):
    r = requests.get(
        "https://api.crossref.org/works",
        params={"sample": 100, "filter": "type:journal-article,from-pub-date:2019-01-01,until-pub-date:2024-12-31,has-references:true",
                "select": "DOI"},
        headers=sources.HEADERS, timeout=120,
    )
    out = []
    for it in r.json()["message"]["items"]:
        d = sources.norm_doi(it["DOI"])
        good, n, w = ok_size(d)
        if good:
            out.append({"id": f"A{len(out)+1:02d}", "stratum": "random", "source_doi": d, "title": w.get("title"), "refs": n})
            if len(out) == k:
                break
    return out


def stratum_b(retracted, k=10):
    out = []
    for f in FAMOUS:
        if f not in retracted:
            print("skip (not a retraction in RW):", f)
            continue
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{f}/citations"
        data = []
        for attempt in range(6):
            r = requests.get(url, params={"fields": "externalIds,year", "limit": 200}, headers=sources.HEADERS, timeout=60)
            if r.status_code == 200:
                data = r.json().get("data") or []
                break
            time.sleep(2 ** attempt)
        for c in data:
            cp = c.get("citingPaper") or {}
            d = sources.norm_doi((cp.get("externalIds") or {}).get("DOI"))
            if not d or not cp.get("year") or not (2019 <= cp["year"] <= 2024):
                continue
            good, n, w = ok_size(d)
            if good and f in w.get("refs", []):
                out.append({"id": f"B{len(out)+1:02d}", "stratum": "cites-famous-retraction", "via": f,
                            "source_doi": d, "title": w.get("title"), "refs": n})
                break
        if len(out) == k:
            break
    return out


if __name__ == "__main__":
    if OUT.exists():
        raise SystemExit("cases.json already frozen; delete it on purpose to reselect")
    rw = sources.load_retractions()
    a = stratum_a()
    b = stratum_b(set(rw))
    for i, c in enumerate(a):
        c["split"] = "eval" if i < 8 else "holdout"
    for i, c in enumerate(b):
        c["split"] = "eval" if i < len(b) - 2 else "holdout"
    OUT.write_text(json.dumps({"frozen": time.strftime("%Y-%m-%d"), "cases": a + b}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(len(a), len(b))

#!/usr/bin/env python3
"""Add the newest CMS month to the Rhode Island history files used by the sales page.

Downloads the four CMS files the builder uses (ProviderInfo, HealthCitations, Penalties, Ownership)
from CMS's public Provider Data catalog, keeps the Rhode Island rows, standardizes the column names the
same way the Colab notebook does, and appends them to pipeline/history/*.csv.gz with a snapshot_date.

Prints "NOTHING NEW" and exits 0 if that CMS month is already in the history.
Exits 1 with a plain message if anything looks wrong, so nothing is published.
Usage: update_history.py [--force]
"""
import csv, gzip, io, json, os, re, sys, urllib.request
from datetime import datetime
import pandas as pd

CATALOG = "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items?show-reference-ids=false"
HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
FILES = {"providerinfo": "ProviderInfo", "healthcitations": "HealthCitations",
         "penalties": "Penalties", "ownership": "Ownership"}
STATE_COLS = ["state", "provider_state"]
CCN_COLS = ["cms_certification_number_ccn", "federal_provider_number", "provnum", "ccn", "provider_id"]


def die(msg):
    print("ERROR:", msg)
    sys.exit(1)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "abc-ri-update/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def norm_col(c):
    return re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")


def to_std(raw_bytes, snapshot_date, source):
    """Raw CMS CSV bytes -> RI-only frame in the history schema."""
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(text), dtype=str, low_memory=False)
    df.columns = [norm_col(c) for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]
    ccn = next((c for c in CCN_COLS if c in df.columns), None)
    if ccn is None:
        die(f"{source}: no facility ID column found. Columns: {list(df.columns)[:12]}")
    st = next((c for c in STATE_COLS if c in df.columns), None)
    keep = df[st].fillna("").str.strip().str.upper().eq("RI") if st else df[ccn].fillna("").str.strip().str.zfill(6).str.startswith("41")
    df = df[keep].copy()
    df.insert(0, "ccn_std", df[ccn].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(6))
    df.insert(0, "snapshot_date", snapshot_date)
    df.insert(2, "snapshot", f"nursing-homes_{snapshot_date[:4]}")
    df.insert(3, "source_path", source)
    return df


def append(name, new):
    path = os.path.join(HIST, name + ".csv.gz")
    old = pd.read_csv(path, dtype=str, low_memory=False)
    snap = new["snapshot_date"].iloc[0]
    old = old[old["snapshot_date"] != snap]            # re-running a month replaces it
    missing = [c for c in old.columns if c not in new.columns]
    extra = [c for c in new.columns if c not in old.columns]
    if len(missing) > 0.25 * len(old.columns):
        die(f"{name}: new CMS file is missing {len(missing)} of {len(old.columns)} expected columns, e.g. {missing[:6]}. CMS may have renamed columns.")
    if extra:
        print(f"NOTE {name}: {len(extra)} new CMS column(s) not kept: {extra[:6]}")
    if missing:
        print(f"NOTE {name}: {len(missing)} expected column(s) absent this month (left blank): {missing[:6]}")
    out = pd.concat([old, new.reindex(columns=old.columns)], ignore_index=True)
    out.to_csv(path, index=False, compression="gzip")
    print(f"{name}: added {len(new)} RI rows for {snap}; history now {len(out)} rows")


def main(force=False):
    items = json.loads(get(CATALOG))
    nh = [i for i in items if "nursing home" in json.dumps([i.get("theme"), i.get("title")]).lower()]
    urls, newest = {}, ""
    for i in nh:
        for d in i.get("distribution", []) or []:
            u = d.get("downloadURL") or ""
            base = os.path.basename(u.split("?")[0])
            for key, frag in FILES.items():
                if base.lower().endswith(".csv") and re.search(r"(^|_|-)" + frag + r"(_|\.|$)", base, re.I):
                    urls[key] = (u, base)
                    newest = max(newest, str(i.get("modified", ""))[:10])
    miss = [k for k in FILES if k not in urls]
    if miss:
        die(f"CMS catalog did not list: {miss}")
    snapshot_date = newest or datetime.now().strftime("%Y-%m-%d")
    raws = {k: get(u) for k, (u, _) in urls.items()}
    # which month is this? read it from the provider file
    probe = to_std(raws["providerinfo"], snapshot_date, urls["providerinfo"][1])
    col = next((c for c in ("processing_date", "filedate") if c in probe.columns), None)
    if col is None or probe[col].dropna().empty:
        die("could not read the processing date from the CMS provider file")
    month = pd.to_datetime(probe[col], errors="coerce", format="mixed").dt.strftime("%Y-%m").mode().iloc[0]
    # Use the date CMS stamps on the data (like the earlier months), not the catalog's "modified" date.
    pdate = pd.to_datetime(probe[col], errors="coerce", format="mixed").dropna()
    snapshot_date = pdate.dt.strftime("%Y-%m-%d").mode().iloc[0]
    have = pd.read_csv(os.path.join(HIST, "providerinfo.csv.gz"), dtype=str, usecols=["snapshot_date"])["snapshot_date"]
    have_months = {d[:7] for d in have.unique()}
    if month in have_months and not force:
        print(f"NOTHING NEW: CMS month {month} is already in the history.")
        return
    print(f"catalog date {newest}; data date {snapshot_date}; CMS month {month}; newest saved {have.max()}; RI rows {len(probe)}")
    if snapshot_date <= have.max() and not force:
        die(f"new data is dated {snapshot_date}, not later than the newest saved ({have.max()}). Use force if this is intended.")
    if len(probe) < 50:
        die(f"only {len(probe)} Rhode Island providers found in the new CMS file (expected about 70-90)")
    for key, (u, base) in urls.items():
        append(key, to_std(raws[key], snapshot_date, base))
    print(f"READY: added CMS month {month} (snapshot {snapshot_date}).")


if __name__ == "__main__":
    main(force="--force" in sys.argv)

"""Second pass for addresses the Census geocoder did not match: OpenStreetMap Nominatim (one request a second,
per its usage policy). Only addresses found in the records are looked up. Updates data/county/locations.json."""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import county_locate as C  # noqa: E402

out = json.loads(C.OUT.read_text(encoding="utf-8"))
for deal_dir in sorted(p for p in C.COUNTY.iterdir() if p.is_dir()):
    slug = deal_dir.name
    if slug in out:
        continue
    found, where, cities = C.candidates(deal_dir)
    if not found:
        continue
    addr, n = found.most_common(1)[0]
    if n < 3:
        print(f"{slug}: only {n} mention of {addr}; left off the map")
        continue
    city = max((c for (a, c) in cities if a == addr), key=lambda c: cities[(addr, c)], default="")
    for c in [city, "New Carrollton", "Hyattsville", ""]:
        q = urllib.parse.urlencode({"q": f"{addr}, {c + ', ' if c else ''}Prince George's County, MD", "format": "json", "limit": 1, "countrycodes": "us"})
        req = urllib.request.Request(f"https://nominatim.openstreetmap.org/search?{q}", headers={"User-Agent": "promise-ledger-geocode/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
        time.sleep(1.1)
        if res:
            out[slug] = {"address": addr, "city": c, "lat": round(float(res[0]["lat"]), 5), "lon": round(float(res[0]["lon"]), 5),
                         "matched": res[0]["display_name"], "geocoder": "OpenStreetMap Nominatim", "source": where[addr]}
            print(f"{slug}: {res[0]['display_name'][:90]}")
            break
    else:
        print(f"{slug}: no match for {addr}")
C.OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(out), "located")

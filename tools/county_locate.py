"""Finds each county agreement's property address in its own records and geocodes it with the U.S. Census
geocoder (public, no key). Writes data/county/locations.json; every location names the record and page it came from.

  python tools/county_locate.py            # find candidates and geocode
  python tools/county_locate.py --dry-run  # only print the address candidates

Addresses are read, never guessed: a deal with no street address in its records is left off the map.
"""
import json, re, sys, time, urllib.parse, urllib.request
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
COUNTY = ROOT / "data" / "county"
OUT = COUNTY / "locations.json"
SUFFIX = r"(?:Avenue|Ave\.?|Road|Rd\.?|Street|St\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Lane|Ln\.?|Parkway|Pkwy\.?|Highway|Hwy\.?|Way|Place|Pl\.?|Court|Ct\.?|Terrace|Circle|Pike)"
ADDR = re.compile(rf"\b(\d{{3,5}}(?:\s*[-–]\s*\d{{3,5}})?)\s+((?:[NSEW]\.?\s+)?(?:[A-Z][A-Za-z'.]+\s+){{0,4}}{SUFFIX})(?![A-Za-z])")
CITY = re.compile(r"\b(Capitol Heights|Bowie|Hyattsville|Upper Marlboro|Largo|Lanham|New Carrollton|Fort Washington|Greenbelt|Laurel|"
                  r"Landover|Oxon Hill|Temple Hills|District Heights|Glenarden|Riverdale|Cottage City|Brentwood|Mount Rainier|"
                  r"College Park|Beltsville|Clinton|Suitland|Forestville|Glenn Dale|Mitchellville|Accokeek|Adelphi|Cheverly|Bladensburg|"
                  r"Seat Pleasant|Hillcrest Heights|Camp Springs|Forest Heights|Edmonston|Lanham-Seabrook|Kettering|Springdale|Fairmount Heights)\b")
NOISE = re.compile(r"(?i)suite|floor|p\.?\s*o\.?\s*box|largo, md 20774|14741 governor oden bowie|1301 mccormick|9200 basil")


def records(deal_dir):
    m = json.loads((deal_dir / "manifest.json").read_text(encoding="utf-8"))
    for d in m["documents"]:
        p = deal_dir / d["file"]
        if p.exists():
            yield m, d, p


def candidates(deal_dir):
    found = Counter(); where = {}; cities = Counter()
    for m, d, p in records(deal_dir):
        try:
            pages = PdfReader(str(p)).pages
        except Exception:
            continue
        for n, page in enumerate(pages, 1):
            text = " ".join((page.extract_text() or "").split())
            for mt in ADDR.finditer(text):
                span = text[max(0, mt.start() - 60):mt.end() + 60]
                if NOISE.search(span):
                    continue  # Government offices and mailing addresses, not the property.
                addr = f"{mt.group(1)} {mt.group(2)}".replace("–", "-")
                found[addr] += 1
                where.setdefault(addr, {"record": d["title"], "type": d["type"], "page": n, "context": span})
                c = CITY.search(span)
                if c: cities[(addr, c.group(1))] += 1
    return found, where, cities


def geocode(street, city):
    q = urllib.parse.urlencode({"street": street, "city": city or "", "state": "MD", "benchmark": "Public_AR_Current", "format": "json"})
    url = f"https://geocoding.geo.census.gov/geocoder/locations/address?{q}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "promise-ledger-geocode"}), timeout=30) as r:
        res = json.load(r)["result"]["addressMatches"]
    if not res: return None
    a = res[0]
    return {"lat": round(a["coordinates"]["y"], 5), "lon": round(a["coordinates"]["x"], 5), "matched": a["matchedAddress"]}


def main():
    dry = "--dry-run" in sys.argv
    out = json.loads(OUT.read_text()) if OUT.exists() else {}
    for deal_dir in sorted(p for p in COUNTY.iterdir() if p.is_dir()):
        slug = deal_dir.name
        found, where, cities = candidates(deal_dir)
        top = found.most_common(4)
        print(f"\n{slug}")
        for addr, n in top:
            city = max((c for (a, c) in cities if a == addr), key=lambda c: cities[(addr, c)], default="")
            print(f"  {n:>3}x {addr}  [{city}]  ({where[addr]['type']} p.{where[addr]['page']})")
        if dry or not top or slug in out:
            continue
        addr = top[0][0]
        city = max((c for (a, c) in cities if a == addr), key=lambda c: cities[(addr, c)], default="")
        street = addr.split("-")[0].strip() if re.match(r"^\d+\s*-", addr) else addr
        street = re.sub(r"^(\d+)\s*-\s*\d+", r"\1", street)
        try:
            g = geocode(street, city)
        except Exception as err:
            print("  geocode failed:", type(err).__name__); g = None
        time.sleep(1)
        if g:
            out[slug] = {"address": addr, "city": city, **g, "source": where[addr]}
            print(f"  -> {g['matched']} ({g['lat']}, {g['lon']})")
        else:
            print("  -> no match")
    if not dry:
        OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

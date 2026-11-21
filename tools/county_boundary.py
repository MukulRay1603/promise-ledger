"""Fetches the Prince George's County and Washington, DC outlines from the Census TIGERweb service (public domain),
simplified, and writes data/county/boundary.json. Also marks street-level geocodes in locations.json as approximate."""
import json, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query?"
shapes = {}
for geoid, name in [("24033", "Prince George's County"), ("11001", "Washington, DC")]:
    q = urllib.parse.urlencode({"where": f"GEOID='{geoid}'", "outFields": "NAME", "f": "geojson", "returnGeometry": "true",
                                "maxAllowableOffset": "0.0008", "outSR": "4326"})
    with urllib.request.urlopen(urllib.request.Request(URL + q, headers={"User-Agent": "promise-ledger"}), timeout=60) as r:
        g = json.load(r)["features"][0]["geometry"]
    rings = g["coordinates"] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]
    shapes[name] = [[[round(x, 4), round(y, 4)] for x, y in ring] for ring in rings]
    print(name, sum(len(r) for r in rings), "points")
out = {"source": "U.S. Census Bureau TIGERweb, simplified", "shapes": shapes}
(ROOT / "data" / "county" / "boundary.json").write_text(json.dumps(out, separators=(",", ":")))

loc_path = ROOT / "data" / "county" / "locations.json"
loc = json.loads(loc_path.read_text(encoding="utf-8"))
for v in loc.values():
    v["approx"] = v.get("geocoder") == "OpenStreetMap Nominatim" and not v["matched"][:1].isdigit()
    v.setdefault("geocoder", "U.S. Census Geocoder")
loc_path.write_text(json.dumps(loc, indent=1, ensure_ascii=False), encoding="utf-8")
print(sum(v["approx"] for v in loc.values()), "approximate of", len(loc))

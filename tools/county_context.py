"""Map context from Census TIGERweb (public domain): interstates and US highways around the county agreements, and
town label points. Adds "roads" and "places" to data/county/boundary.json."""
import json, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "county" / "boundary.json"
BOX = (-77.13, 38.70, -76.60, 39.12)  # west, south, east, north
TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"


def query(service, layer, **params):
    q = {"f": "geojson", "outSR": "4326", "returnGeometry": "true", "geometryType": "esriGeometryEnvelope",
         "geometry": ",".join(map(str, BOX)), "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", **params}
    url = f"{TIGER}{service}/MapServer/{layer}/query?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "promise-ledger"}), timeout=90) as r:
        return json.load(r)["features"]


roads = {}
for f in query("Transportation", 1, outFields="NAME,RTTYP", maxAllowableOffset="0.0006"):
    name = f["properties"].get("NAME") or ""
    g = f["geometry"]
    lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
    roads.setdefault(name, []).extend([[round(x, 4), round(y, 4)] for x, y in line] for line in lines)
print("roads:", {k: len(v) for k, v in roads.items()})
# Keep the routes people navigate by: interstates, US highways and a few main state routes, under short names.
import re
major = {}
for name, lines in roads.items():
    for pattern, kind, label in ((r"^I- (\d+)$", "interstate", "I-{}"), (r"^US Hwy (\d+)$", "us", "US {}"),
                                 (r"^State Hwy (4|5|295|202|214)$", "state", "MD {}")):
        m = re.match(pattern, name)
        if m:
            major.setdefault(label.format(m.group(1)), {"kind": kind, "lines": []})["lines"] += lines
            break
roads = major

WANT = ["Bowie", "College Park", "Greenbelt", "Hyattsville", "Largo", "Upper Marlboro", "Laurel", "Landover", "Capitol Heights",
        "Fort Washington", "Oxon Hill", "New Carrollton", "District Heights", "Lanham", "Suitland", "Clinton", "Beltsville", "Temple Hills"]
places = {}
for layer in (4, 5):  # Incorporated places, census designated places.
    try:
        feats = query("Places_CouSub_ConCity_SubMCD", layer, outFields="BASENAME,CENTLAT,CENTLON", returnGeometry="false")
    except Exception as err:
        print("places layer", layer, "failed", type(err).__name__); continue
    for f in feats:
        p = f["properties"]
        if p.get("BASENAME") in WANT and p["BASENAME"] not in places:
            places[p["BASENAME"]] = [round(float(p["CENTLON"]), 4), round(float(p["CENTLAT"]), 4)]
print("places:", sorted(places))

data = json.loads(PATH.read_text())
data["roads"] = roads
data["places"] = places
data["source"] = "U.S. Census Bureau TIGERweb (county and DC outlines, primary roads, place points), simplified"
PATH.write_text(json.dumps(data, separators=(",", ":")))
print(PATH.stat().st_size, "bytes")

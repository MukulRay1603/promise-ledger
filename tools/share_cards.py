"""Link-preview images (1200x630) for every county agreement and the site, written to app/static/og/.
Each card shows only numbers from the county board, which come from checked quotes. Re-run after a county re-read:

  python tools/share_cards.py http://localhost:8780

Needs Pillow on the machine that makes the cards (not on the server: the cards are static files)."""
import json, os, sys, textwrap, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "static" / "og"
FONTS = Path(os.environ.get("CARD_FONTS", "C:/Windows/Fonts"))
W, H = 1200, 630
NAVY, INK, MUTED = (15, 23, 42), (248, 250, 252), (176, 190, 205)
TEAL, TEAL_INK, AMBER = (45, 212, 191), (94, 234, 212), (252, 211, 77)


def font(weight, size):
    name = {"bold": "segoeuib.ttf", "semi": "seguisb.ttf", "regular": "segoeui.ttf"}[weight]
    path = FONTS / name
    return ImageFont.truetype(str(path if path.exists() else FONTS / "segoeui.ttf"), size)


def base():
    img = Image.new("RGB", (W, H), NAVY)
    glow = Image.new("RGB", (W, H), NAVY)
    g = ImageDraw.Draw(glow)
    g.ellipse((-260, -320, 640, 420), fill=(20, 92, 90))
    g.ellipse((760, 330, 1460, 900), fill=(26, 60, 70))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(140)), 0.9)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 40):  # Faint grid, like a ledger.
        d.line([(x, 0), (x, H)], fill=(21, 30, 49), width=1)
    for y in range(0, H, 40):
        d.line([(0, y), (W, y)], fill=(21, 30, 49), width=1)
    # Wordmark.
    d.rounded_rectangle((64, 56, 108, 100), radius=10, fill=(15, 118, 110))
    d.rectangle((77, 66, 95, 90), outline=INK, width=3)
    d.line((81, 74, 91, 74), fill=INK, width=2); d.line((81, 80, 91, 80), fill=INK, width=2)
    d.text((124, 58), "Promise Ledger", font=font("bold", 34), fill=INK)
    return img, d


def pill(d, x, y, text, fg, bg):
    f = font("semi", 22)
    w = d.textlength(text, font=f)
    d.rounded_rectangle((x, y, x + w + 36, y + 42), radius=21, fill=bg)
    d.ellipse((x + 14, y + 17, x + 22, y + 25), fill=fg)
    d.text((x + 30, y + 7), text, font=f, fill=fg)
    return x + w + 36


def stat(d, x, y, value, label, color):
    d.text((x, y), value, font=font("bold", 64), fill=color)
    d.text((x, y + 82), label, font=font("regular", 24), fill=MUTED)


def deal_card(r, totals):
    img, d = base()
    pill(d, 64, 132, "Real public records · Prince George's County, MD", TEAL_INK, (19, 58, 66))
    lines = textwrap.wrap(r["name"], 26)[:2]
    y = 200
    for line in lines:
        d.text((64, y), line, font=font("bold", 66), fill=INK); y += 78
    y = max(y + 18, 380)
    soon = r.get("term_end") and r["term_end"] < "2041-01-01"
    stat(d, 64, y, f"{r['homes']:,}" if r.get("homes") else "Not stated", "affordable homes", TEAL_INK if r.get("homes") else MUTED)
    term = f"{r['term_end'][:4]}{'+' if r.get('term_end_estimated') else ''}" if r.get("term_end") else "—"
    stat(d, 460, y, term, "stated term runs to", AMBER if soon else TEAL_INK)
    found = sum(1 for v in r["found"].values() if v)
    stat(d, 820, y, f"{found} of {len(r['found'])}", "key terms found in the records", AMBER if found < len(r["found"]) else TEAL_INK)
    d.text((64, 560), f"Council file {r.get('file') or ''} · every number opens its quote and page", font=font("regular", 22), fill=MUTED)
    return img


def site_card(t):
    img, d = base()
    pill(d, 64, 132, "AI reads · Code checks · People decide", TEAL_INK, (19, 58, 66))
    d.text((64, 196), "Public support should come", font=font("bold", 70), fill=INK)
    d.text((64, 280), "with a ", font=font("bold", 70), fill=INK)
    x = 64 + d.textlength("with a ", font=font("bold", 70))
    d.text((x, 280), "receipt.", font=font("bold", 70), fill=TEAL_INK)
    stat(d, 64, 400, str(t["deals"]), "real county agreements", INK)
    stat(d, 400, 400, f"{t['homes']:,}", "affordable homes stated", TEAL_INK)
    stat(d, 780, 400, f"{t['pages']:,}", "pages of records read", INK)
    return img


def main():
    url = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8780").rstrip("/")
    board = json.load(urllib.request.urlopen(f"{url}/api/county", timeout=60))
    OUT.mkdir(parents=True, exist_ok=True)
    site_card(board["totals"]).save(OUT / "site.png", optimize=True)
    for r in board["deals"]:
        if r.get("records_read"):
            deal_card(r, board["totals"]).save(OUT / f"{r['id']}.png", optimize=True)
    print(len(list(OUT.glob("*.png"))), "cards in", OUT)


if __name__ == "__main__":
    main()

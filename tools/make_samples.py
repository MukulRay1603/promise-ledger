"""Build the sample deal PDFs, manifests and gold answers in data/samples/.

Everything here is fictional: the City of Lantern Bay, Bayside County, every
company, address, date, number and sentence. No text is copied from any real
record. Names are generic roles only.

Run from the repo root:  python tools/make_samples.py [output_dir]
Needs reportlab (to draw) and pypdf (to check page counts).
Output is byte-for-byte deterministic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab import rl_config

rl_config.invariant = 1  # no timestamps or random ids, so output is repeatable

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import inch  # noqa: E402
from reportlab.pdfgen import canvas as rl_canvas  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "samples"
DEMO_DIR = ROOT / "data" / "demo"

FOOTER = "SAMPLE DOCUMENT · fictional · for demonstration"
NOTICE = (
    "Fictional sample data for demonstration. Lantern Bay, Bayside County and every "
    "company, date, number and quote in these documents are made up."
)
TERMS = ["units", "income_basis", "rent_limits", "term", "responsible_party", "reporting", "remedies"]
STAGES = ["proposed", "supported", "signed", "delivered"]

INK = colors.HexColor("#1b1f24")
GREY = colors.HexColor("#5b6470")
RULE = colors.HexColor("#9aa3ad")
NAVY = colors.HexColor("#14365a")
TEAL = colors.HexColor("#1f7a72")
SAND = colors.HexColor("#f3efe6")

# ---------------------------------------------------------------------------
# Text styles for letter-size records
# ---------------------------------------------------------------------------
BODY = ParagraphStyle("body", fontName="Times-Roman", fontSize=11, leading=14.5, textColor=INK,
                      alignment=TA_LEFT, spaceAfter=7)
INDENT = ParagraphStyle("indent", parent=BODY, leftIndent=22)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=9, leading=11.5, textColor=GREY, spaceAfter=4)
HEAD = ParagraphStyle("head", parent=BODY, fontName="Times-Bold", fontSize=11.5, spaceBefore=6, spaceAfter=5)
TITLE = ParagraphStyle("title", parent=BODY, fontName="Times-Bold", fontSize=13.5, leading=17,
                       alignment=TA_CENTER, spaceAfter=4)
SUBTITLE = ParagraphStyle("subtitle", parent=BODY, alignment=TA_CENTER, spaceAfter=10)
LH_ORG = ParagraphStyle("lh_org", parent=BODY, fontName="Times-Bold", fontSize=15, leading=18,
                        alignment=TA_CENTER, spaceAfter=1, textColor=NAVY)
LH_SUB = ParagraphStyle("lh_sub", parent=BODY, fontSize=10, leading=12.5, alignment=TA_CENTER,
                        spaceAfter=0, textColor=GREY)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=10, leading=12.5, spaceAfter=0)
CELL_B = ParagraphStyle("cell_b", parent=CELL, fontName="Times-Bold")
SIG = ParagraphStyle("sig", parent=BODY, fontSize=10.5, leading=13.5, spaceAfter=0)
STAMP = ParagraphStyle("stamp", parent=BODY, fontName="Helvetica-Bold", fontSize=10, leading=13,
                       alignment=TA_CENTER, textColor=colors.HexColor("#8a1c1c"), spaceAfter=0)


def para(text: str, style=BODY, bold: str | None = None) -> Paragraph:
    """A paragraph of plain text. `bold` is an optional label printed before it."""
    body = escape(text)
    if bold:
        body = f"<b>{escape(bold)}</b> {body}"
    return Paragraph(body, style)


def memo_table(rows: list[tuple[str, str]]) -> Table:
    data = [[para(k, CELL_B), para(v, CELL)] for k, v in rows]
    t = Table(data, colWidths=[1.05 * inch, 5.35 * inch], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def grid_table(rows: list[list[str]], widths: list[float]) -> Table:
    data = [[para(c, CELL_B if i == 0 else CELL) for c in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=[w * inch for w in widths], hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, RULE),
        ("BACKGROUND", (0, 0), (-1, 0), SAND),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def sig_block(lines: list[str]) -> list:
    out = []
    for line in lines:
        if line == "[signature on file]":
            out.append(para(line, ParagraphStyle("sigfile", parent=SIG, fontName="Times-Italic",
                                                 textColor=GREY)))
            out.append(HRFlowable(width=2.6 * inch, thickness=0.6, color=INK, hAlign="LEFT",
                                  spaceBefore=1, spaceAfter=2))
        else:
            out.append(para(line, SIG))
    return out


def two_sigs(left: list[str], right: list[str]) -> Table:
    t = Table([[sig_block(left), sig_block(right)]], colWidths=[3.2 * inch, 3.2 * inch], hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def stamp(text: str) -> Table:
    t = Table([[para(text, STAMP)]], colWidths=[3.6 * inch], hAlign="CENTER")
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#8a1c1c")),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def letterhead(org: str, sub: str, address: str) -> list:
    return [para(org, LH_ORG), para(sub, LH_SUB), para(address, LH_SUB), Spacer(1, 5),
            HRFlowable(width="100%", thickness=1.4, color=NAVY, spaceAfter=1),
            HRFlowable(width="100%", thickness=0.4, color=NAVY, spaceAfter=12)]


def build_record(path: Path, pages: list[list], running: str) -> int:
    """Draw a letter-size record. Each item of `pages` is one page of flowables."""
    total = len(pages)

    def on_page(c, doc):
        c.saveState()
        n = c.getPageNumber()
        c.setFont("Helvetica", 7.5)
        c.setFillColor(GREY)
        c.drawCentredString(letter[0] / 2, 0.5 * inch, FOOTER)
        c.drawRightString(letter[0] - inch, 0.5 * inch, f"Page {n} of {total}")
        if n > 1:
            c.setFont("Times-Italic", 9)
            c.drawRightString(letter[0] - inch, letter[1] - 0.6 * inch, running)
        c.restoreState()

    story = []
    for i, page in enumerate(pages):
        if i:
            story.append(PageBreak())
        story.extend(page)
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=inch, rightMargin=inch,
                            topMargin=0.85 * inch, bottomMargin=0.85 * inch,
                            title=running, author="Sample generator", subject=FOOTER,
                            creator="tools/make_samples.py")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return total


# ---------------------------------------------------------------------------
# Slide decks (16:9, as if exported from presentation software)
# ---------------------------------------------------------------------------
SLIDE = (960, 540)
S_TITLE = ParagraphStyle("s_title", fontName="Helvetica-Bold", fontSize=30, leading=35, textColor=NAVY)
S_BULLET = ParagraphStyle("s_bullet", fontName="Helvetica", fontSize=21, leading=28, textColor=INK,
                          leftIndent=26, bulletIndent=0, spaceAfter=14,
                          bulletFontName="Helvetica", bulletFontSize=21)
S_COVER = ParagraphStyle("s_cover", fontName="Helvetica-Bold", fontSize=40, leading=46, textColor=colors.white)
S_COVER_SUB = ParagraphStyle("s_cover_sub", fontName="Helvetica", fontSize=20, leading=26,
                             textColor=colors.HexColor("#d6e4f0"))


def build_slides(path: Path, slides: list[dict], deck: str) -> int:
    w, h = SLIDE
    c = rl_canvas.Canvas(str(path), pagesize=SLIDE, invariant=1)
    c.setTitle(deck)
    c.setAuthor("Sample generator")
    c.setSubject(FOOTER)
    c.setCreator("tools/make_samples.py")
    for n, s in enumerate(slides, start=1):
        if s.get("cover"):
            c.setFillColor(NAVY)
            c.rect(0, 0, w, h, stroke=0, fill=1)
            c.setFillColor(TEAL)
            c.rect(0, 150, w, 8, stroke=0, fill=1)
            y = 380
            for text, style in [(s["title"], S_COVER)] + [(t, S_COVER_SUB) for t in s.get("lines", [])]:
                p = Paragraph(escape(text), style)
                _, ph = p.wrap(w - 140, h)
                p.drawOn(c, 70, y - ph)
                y -= ph + 14
            c.setFillColor(colors.HexColor("#d6e4f0"))
        else:
            c.setFillColor(colors.white)
            c.rect(0, 0, w, h, stroke=0, fill=1)
            c.setFillColor(NAVY)
            c.rect(0, h - 14, w, 14, stroke=0, fill=1)
            c.setFillColor(TEAL)
            c.rect(60, h - 112, 70, 5, stroke=0, fill=1)
            p = Paragraph(escape(s["title"]), S_TITLE)
            _, ph = p.wrap(w - 120, h)
            p.drawOn(c, 60, h - 60 - ph)
            y = h - 140
            for b in s.get("bullets", []):
                p = Paragraph(escape(b), S_BULLET, bulletText="•")
                _, ph = p.wrap(w - 150, h)
                p.drawOn(c, 70, y - ph)
                y -= ph + 16
            if s.get("note"):
                p = Paragraph(escape(s["note"]), ParagraphStyle("s_note", fontName="Helvetica-Oblique",
                                                                 fontSize=13, leading=17, textColor=GREY))
                _, ph = p.wrap(w - 140, h)
                p.drawOn(c, 70, 70)
            c.setFillColor(GREY)
        c.setFont("Helvetica", 9)
        c.drawCentredString(w / 2, 22, FOOTER)
        c.drawRightString(w - 30, 22, str(n))
        c.drawString(30, 22, deck)
        c.showPage()
    c.save()
    return len(slides)


# ---------------------------------------------------------------------------
# Shared letterheads
# ---------------------------------------------------------------------------
CITY_HCD = ("CITY OF LANTERN BAY", "Department of Housing and Community Development",
            "100 Harbor Street, Lantern Bay · Bayside County")
CITY_CLERK = ("CITY OF LANTERN BAY", "Office of the City Clerk",
              "100 Harbor Street, Lantern Bay · Bayside County")
HWP = ("HARBOR WALK PARTNERS LLC", "Residential development",
       "40 Old Ferry Road, Suite 2, Lantern Bay")


def claim(cid, term, quote, file, page, stage, wording, value, note=""):
    return {"id": cid, "term": term, "quote": quote, "file": file, "page": page, "stage": stage,
            "wording": wording, "value": value, "review_note": note}


# ---------------------------------------------------------------------------
# Deal 1: Harbor Walk (the existing demo story, as PDFs)
# ---------------------------------------------------------------------------
def harbor_walk() -> dict:
    packet = json.loads((DEMO_DIR / "packet.json").read_text(encoding="utf-8"))
    demo = json.loads((DEMO_DIR / "claims.json").read_text(encoding="utf-8"))
    text = {d["id"]: {p["page"]: p["paragraphs"][1:] for p in d["pages"]} for d in packet["documents"]}
    files = {"staff-summary": "01-staff-summary.pdf", "draft-letter": "02-draft-letter.pdf",
             "developer-slides": "03-developer-slides.pdf", "minutes": "04-council-minutes.pdf",
             "later-letter": "05-developer-letter.pdf"}
    T = text  # short alias: T[doc][page][i] is a sentence from the demo packet

    staff = [
        [*letterhead(*CITY_HCD),
         para("STAFF SUMMARY", TITLE),
         memo_table([("To:", "Mayor and City Council"), ("From:", "Housing Director"),
                     ("Date:", "February 3, 2025"), ("Subject:", "Harbor Walk tax request"),
                     ("Item type:", "Information and recommendation")]),
         HRFlowable(width="100%", thickness=0.5, color=RULE, spaceBefore=6, spaceAfter=10),
         para("1. Request", HEAD),
         para(T["staff-summary"][1][0]),
         para("The request was received on January 14, 2025 and is scheduled for Council discussion "
              "on March 11, 2025."),
         para("2. Affordable homes described by the developer", HEAD),
         para(T["staff-summary"][1][1]),
         para(T["staff-summary"][1][2]),
         para("Rent levels for these homes were not described in the request."),
         para("3. Site", HEAD),
         para("The Old Ferry lot is a 2.4-acre parcel zoned for mixed residential use. The site has "
              "been vacant since the ferry terminal closed."),
         ],
        [para("4. Length of the income limits", HEAD),
         para(T["staff-summary"][2][0]),
         para("5. Written terms", HEAD),
         para(T["staff-summary"][2][1]),
         para("Reporting and enforcement provisions have not yet been proposed."),
         para("6. Fiscal note", HEAD),
         para("The request is for a 50 percent reduction in property taxes on the new building for "
              "20 years. Staff estimates the reduction at about $270,000 per year, based on a "
              "projected taxable value of $45 million."),
         para("7. Recommendation", HEAD),
         para(T["staff-summary"][2][2]),
         Spacer(1, 10),
         para("Prepared by: Housing Program Manager", SIG),
         para("Reviewed by: Housing Director", SIG),
         para("Attachments: none", SIG),
         ],
    ]
    draft = [
        [*letterhead(*HWP),
         stamp(T["draft-letter"][1][0]),
         Spacer(1, 12),
         para("February 20, 2025"),
         para("Housing Director", SIG), para("City of Lantern Bay", SIG),
         para("100 Harbor Street", SIG), para("Lantern Bay", SIG), Spacer(1, 10),
         para("Re: Harbor Walk, Old Ferry lot"),
         para("Dear Housing Director:"),
         para(T["draft-letter"][1][1]),
         para(T["draft-letter"][1][2]),
         para(T["draft-letter"][1][3]),
         para("We expect to share a site plan and a construction schedule before the Council meeting."),
         para(T["draft-letter"][1][4]),
         Spacer(1, 6),
         para("Sincerely,", SIG), Spacer(1, 16),
         para("[unsigned draft]", ParagraphStyle("unsig", parent=SIG, fontName="Times-Italic", textColor=GREY)),
         para("Managing Member", SIG), para("Harbor Walk Partners LLC", SIG),
         ],
    ]
    slides = [
        {"cover": True, "title": T["developer-slides"][1][0],
         "lines": [T["developer-slides"][1][1], "Lantern Bay City Council · March 4, 2025"]},
        {"title": T["developer-slides"][2][0],
         "bullets": [T["developer-slides"][2][1], T["developer-slides"][2][2],
                     "Close to the ferry landing, two bus lines and the harbor jobs district."]},
        {"title": T["developer-slides"][3][0].rstrip("."),
         "bullets": [T["developer-slides"][3][1], "Site plan review: spring 2025.",
                     "Construction start: early 2026, subject to approvals."],
         "note": "Illustrative only. Terms are subject to a written agreement."},
    ]
    minutes = [
        [*letterhead(*CITY_CLERK),
         para("MINUTES", TITLE),
         para("Lantern Bay City Council · Regular Meeting · March 11, 2025 · Council Chamber", SUBTITLE),
         para("1. Call to order", HEAD),
         para("The Mayor called the meeting to order at 7:00 p.m."),
         para("2. Roll call", HEAD),
         para(T["minutes"][1][0]),
         para("3. Approval of the agenda", HEAD),
         para("The agenda was approved as posted without objection."),
         para("4. Public hearing: Harbor Walk tax request", HEAD),
         para("The Housing Director summarized the staff summary dated February 3, 2025."),
         para(T["minutes"][1][1]),
         para("Four members of the public spoke on the item. The Mayor closed the hearing at 8:55 p.m."),
         para(T["minutes"][1][2]),
         para("Council Member (Seat 3) moved to support the tax request. Council Member (Seat 5) seconded."),
         para(T["minutes"][1][3]),
         para("Ayes: Seats 1, 2, 3, 5 and 7. Noes: Seats 4 and 6.", INDENT),
         ],
        [para("4. Public hearing: Harbor Walk tax request (continued)", HEAD),
         para(T["minutes"][2][0]),
         para("5. Other business", HEAD),
         para("None."),
         para("6. Adjournment", HEAD),
         para(T["minutes"][2][1]),
         Spacer(1, 14),
         para("Approved by the Council on April 8, 2025.", SIG), Spacer(1, 10),
         *sig_block(["Attest:", "[signature on file]", "City Clerk"]),
         ],
    ]
    later = [
        [*letterhead(*HWP),
         para("September 15, 2025"),
         para("Housing Director", SIG), para("City of Lantern Bay", SIG),
         para("100 Harbor Street", SIG), para("Lantern Bay", SIG), Spacer(1, 10),
         para("Re: Harbor Walk affordable homes"),
         para("Dear Housing Director:"),
         *[para(s) for s in T["later-letter"][1][:5]],
         para("Please contact our office with any questions."),
         Spacer(1, 6),
         para("Sincerely,", SIG), Spacer(1, 6),
         *sig_block(["HARBOR WALK PARTNERS LLC", "[signature on file]", "Managing Member"]),
         ],
    ]
    out = OUT_DIR_CURRENT / "harbor-walk"
    out.mkdir(parents=True, exist_ok=True)
    docs = []
    for doc_id, pages in [("staff-summary", staff), ("draft-letter", draft), ("minutes", minutes),
                          ("later-letter", later)]:
        d = next(x for x in packet["documents"] if x["id"] == doc_id)
        n = build_record(out / files[doc_id], pages, f"{d['type']} · Harbor Walk · {d['date']}")
        docs.append((doc_id, n))
    docs.append(("developer-slides", build_slides(out / files["developer-slides"], slides,
                                                  "Harbor Walk Partners LLC")))
    pages = dict(docs)
    manifest_docs = []
    for d in packet["documents"]:
        manifest_docs.append({"file": files[d["id"]], "id": d["id"], "type": d["type"], "date": d["date"],
                              "title": d["title"], "pages": pages[d["id"]],
                              "signed_by": ["Harbor Walk Partners LLC"] if d["signed"] else []})
    claims = []
    for c in demo["claims"]:
        claims.append(claim(c["id"], c["topic"], c["quote"], files[c["document"]], c["page"],
                            c["status"], c["wording"], c["value"], c["review_note"]))
    gold = {
        "not_located": ["rent_limits", "remedies"],
        "differs": [
            {"term": "income_basis", "values": ["60 percent of area median income",
                                                "80 percent of area median income"],
             "claims": ["c02", "c08", "c14"]},
            {"term": "term", "values": ["30 years", "15 years"], "claims": ["c03", "c09", "c15"]},
        ],
        "stage_notes": demo["stage_notes"],
        "story": "The same 12 homes are described as \"has agreed\", \"will explore\", \"considering\", "
                 "\"understanding\" and \"will provide\". Income basis and term differ between records. "
                 "Rent limits and remedies are not located. Only the developer signed.",
    }
    return finish(out, "Harbor Walk", "harbor-walk", 120, "Harbor Walk Partners LLC", manifest_docs, claims, gold)


# ---------------------------------------------------------------------------
# Deal 2: Beacon Point (clean and complete)
# ---------------------------------------------------------------------------
BP = {
    "support_sr": "Staff recommends that the Council adopt the attached resolution approving a 15-year payment in lieu of taxes for Beacon Point.",
    "units_sr": "The owner will reserve 16 of the 80 homes as affordable homes.",
    "income_sr": "Each affordable home must be leased to a household with income at or below 60 percent of area median income.",
    "rent_sr": "Rents for the affordable homes may not exceed the 60 percent rent limit based on the HUD income limits published each year.",
    "term_sr": "The affordability requirements will last for 30 years from the date the first affordable home is leased.",
    "resp_sr": "The owner, and any later owner of the property, is responsible for meeting these requirements.",
    "report_sr": "The owner will file an annual compliance certificate with the City by March 1 of each year.",
    "remedy_sr": "If a default is not cured within 60 days after written notice, the owner must repay all abated taxes with interest.",
    "support_res": "The City Council approves a payment in lieu of taxes for Beacon Point for a period of 15 years.",
    "units_res": "16 of the 80 homes are reserved as affordable homes",
    "income_res": "each affordable home is leased to a household with income at or below 60 percent of area median income",
    "rent_res": "rents do not exceed the 60 percent rent limit based on the HUD income limits published each year",
    "term_res": "the requirements last for 30 years from the date the first affordable home is leased",
    "resp_res": "the owner and any later owner of the property are responsible for meeting the requirements",
    "report_res": "the owner files an annual compliance certificate with the City by March 1 of each year",
    "remedy_res": "the owner repays all abated taxes with interest if a default is not cured within 60 days after written notice",
    "support_ag": "The Owner shall pay the City an annual payment in lieu of taxes equal to 25 percent of the property taxes that would otherwise be due, for a period of 15 years.",
    "units_ag": "The Owner shall reserve 16 of the 80 homes in the Project as Affordable Homes.",
    "income_ag": "Each Affordable Home shall be leased to a household with income at or below 60 percent of Area Median Income.",
    "rent_ag": "Monthly rent for each Affordable Home, including a utility allowance, shall not exceed the 60 percent rent limit based on the HUD income limits published each year.",
    "term_ag": "The requirements of this Article 3 shall remain in effect for 30 years from the date the first Affordable Home is leased.",
    "resp_ag": "The Owner is responsible for compliance with this Agreement, and this Agreement binds every later owner of the Project.",
    "report_ag": "The Owner shall deliver an annual compliance certificate to the City by March 1 of each year.",
    "notice_ag": "The City shall give the Owner written notice of any default under this Agreement.",
    "remedy_ag": "If a default is not cured within 60 days after written notice, the Owner shall repay all abated taxes with interest.",
}


def beacon_point() -> dict:
    out = OUT_DIR_CURRENT / "beacon-point"
    out.mkdir(parents=True, exist_ok=True)
    f_sr, f_res, f_ag = "01-staff-report.pdf", "02-council-resolution.pdf", "03-pilot-regulatory-agreement.pdf"

    sr = [
        [*letterhead(*CITY_HCD),
         para("STAFF REPORT", TITLE),
         memo_table([("To:", "Mayor and City Council"), ("From:", "Housing Director"),
                     ("Date:", "May 6, 2025"), ("Meeting:", "May 13, 2025, Regular Meeting, Item 7B"),
                     ("Subject:", "Beacon Point payment in lieu of taxes request")]),
         HRFlowable(width="100%", thickness=0.5, color=RULE, spaceBefore=6, spaceAfter=10),
         para("1. Recommendation", HEAD),
         para(BP["support_sr"]),
         para("2. Background", HEAD),
         para("Beacon Point is a proposed building of 80 homes at 2200 Beacon Avenue. The owner, Beacon "
              "Point Housing LLC, has asked that its property taxes be replaced by a smaller annual "
              "payment in lieu of taxes (PILOT)."),
         para("A draft agreement has been negotiated by staff and the owner and is attached to this report."),
         para("3. Affordability terms", HEAD),
         para("The draft agreement contains the following terms."),
         para(BP["units_sr"], INDENT, "3.1 Units."),
         para(BP["income_sr"], INDENT, "3.2 Income basis."),
         ],
        [para(BP["rent_sr"], INDENT, "3.3 Rent limits."),
         para(BP["term_sr"], INDENT, "3.4 Term."),
         para(BP["resp_sr"], INDENT, "3.5 Responsible party."),
         para(BP["report_sr"], INDENT, "3.6 Reporting."),
         para(BP["remedy_sr"], INDENT, "3.7 Remedies."),
         para("4. Fiscal impact", HEAD),
         para("The table below uses the County Assessor's projected taxable value at completion."),
         grid_table([["Item", "Annual amount"],
                     ["Property taxes without the agreement (estimate)", "$412,000"],
                     ["Payment in lieu of taxes (25 percent)", "$103,000"],
                     ["Abated amount", "$309,000"],
                     ["Abated amount over 15 years", "$4,635,000"]], [4.2, 2.2]),
         Spacer(1, 8),
         para("5. Alternatives", HEAD),
         para("The Council may decline the request, or may direct staff to negotiate different terms."),
         ],
        [para("6. Consistency with City policy", HEAD),
         para("The request is consistent with the Lantern Bay Housing Element goal of adding homes "
              "affordable to lower-income households near transit."),
         para("7. Attachments", HEAD),
         para("A. Draft resolution concerning payments in lieu of taxes for Beacon Point", INDENT),
         para("B. Draft PILOT and regulatory agreement", INDENT),
         Spacer(1, 12),
         para("Prepared by: Housing Program Manager", SIG),
         para("Reviewed by: Housing Director", SIG),
         para("Approved for agenda: City Manager", SIG),
         ],
    ]

    res = [
        [*letterhead(*CITY_CLERK),
         para("RESOLUTION NO. 2025-41", TITLE),
         para("A RESOLUTION OF THE CITY COUNCIL OF THE CITY OF LANTERN BAY CONCERNING PAYMENTS IN LIEU "
              "OF TAXES FOR THE BEACON POINT APARTMENTS", SUBTITLE),
         para("WHEREAS, Beacon Point Housing LLC proposes to build 80 homes at 2200 Beacon Avenue; and"),
         para("WHEREAS, the owner has asked the City to accept an annual payment in lieu of taxes; and"),
         para("WHEREAS, the Council received a staff report dated May 6, 2025 and held a public hearing "
              "on May 13, 2025;"),
         para("NOW, THEREFORE, BE IT RESOLVED by the City Council of the City of Lantern Bay as follows:"),
         para(BP["support_res"], BODY, "Section 1."),
         para("The approval in Section 1 is conditioned on an executed agreement between the City and "
              "the owner under which:", BODY, "Section 2."),
         para(f"(a) {BP['units_res']};", INDENT),
         para(f"(b) {BP['income_res']};", INDENT),
         para(f"(c) {BP['rent_res']};", INDENT),
         para(f"(d) {BP['term_res']};", INDENT),
         ],
        [para(f"(e) {BP['resp_res']};", INDENT),
         para(f"(f) {BP['report_res']}; and", INDENT),
         para(f"(g) {BP['remedy_res']}.", INDENT),
         para("The City Manager is authorized to sign the agreement on behalf of the City.", BODY, "Section 3."),
         para("This resolution takes effect immediately.", BODY, "Section 4."),
         Spacer(1, 6),
         para("PASSED AND ADOPTED by the City Council of the City of Lantern Bay on May 13, 2025, by the "
              "following vote:"),
         para("Ayes: 6 · Noes: 1 · Absent: 0 · Abstain: 0", INDENT),
         Spacer(1, 10),
         two_sigs(["[signature on file]", "Mayor"], ["Attest:", "[signature on file]", "City Clerk"]),
         ],
    ]

    ag = [
        [para("PAYMENT IN LIEU OF TAXES AND REGULATORY AGREEMENT", TITLE),
         para("Beacon Point Apartments · 2200 Beacon Avenue, Lantern Bay", SUBTITLE),
         para("This Payment in Lieu of Taxes and Regulatory Agreement (this \"Agreement\") is made as of "
              "July 1, 2025, between the City of Lantern Bay (the \"City\") and Beacon Point Housing LLC "
              "(the \"Owner\")."),
         para("RECITALS", HEAD),
         para("A. The Owner is building an 80-home rental project at 2200 Beacon Avenue (the \"Project\")."),
         para("B. By Resolution No. 2025-41, adopted May 13, 2025, the City Council approved a payment in "
              "lieu of taxes for the Project, subject to this Agreement."),
         para("ARTICLE 1. DEFINITIONS", HEAD),
         para("\"Affordable Home\" means a home in the Project that is subject to Article 3.", INDENT, "1.1"),
         para("\"Area Median Income\" means the median income for Bayside County, adjusted for household "
              "size, as published each year by HUD.", INDENT, "1.2"),
         para("\"HUD\" means the United States Department of Housing and Urban Development.", INDENT, "1.3"),
         para("ARTICLE 2. PAYMENT IN LIEU OF TAXES", HEAD),
         para(BP["support_ag"], INDENT, "2.1"),
         para("Payments are due each year on the date property taxes would otherwise be due.", INDENT, "2.2"),
         ],
        [para("ARTICLE 3. AFFORDABILITY", HEAD),
         para(BP["units_ag"], INDENT, "3.1"),
         para(BP["income_ag"], INDENT, "3.2"),
         para(BP["rent_ag"], INDENT, "3.3"),
         para(BP["term_ag"], INDENT, "3.4"),
         para("Affordable Homes shall be spread through the Project and shall have the same finishes as "
              "other homes of the same size.", INDENT, "3.5"),
         para("ARTICLE 4. RESPONSIBLE PARTY", HEAD),
         para(BP["resp_ag"], INDENT, "4.1"),
         para("The Owner shall give the City 30 days' written notice before any sale of the Project.", INDENT, "4.2"),
         ],
        [para("ARTICLE 5. REPORTING AND RECORDS", HEAD),
         para(BP["report_ag"], INDENT, "5.1"),
         para("The certificate shall state counts only and shall not include household names or other "
              "personal information.", INDENT, "5.2"),
         para("The City may inspect the Owner's leasing records for the Affordable Homes on 10 days' "
              "notice.", INDENT, "5.3"),
         para("ARTICLE 6. DEFAULT AND REMEDIES", HEAD),
         para(BP["notice_ag"], INDENT, "6.1"),
         para(BP["remedy_ag"], INDENT, "6.2"),
         para("The City may also seek any other remedy available at law or in equity.", INDENT, "6.3"),
         para("ARTICLE 7. GENERAL", HEAD),
         para("This Agreement shall be recorded and runs with the land.", INDENT, "7.1"),
         para("This Agreement may be amended only in a writing signed by both parties.", INDENT, "7.2"),
         ],
        [para("SIGNATURES", HEAD),
         para("The parties have signed this Agreement as of the date first written above."),
         Spacer(1, 10),
         two_sigs(["CITY OF LANTERN BAY", "[signature on file]", "City Manager", "Date: July 1, 2025"],
                  ["BEACON POINT HOUSING LLC", "[signature on file]", "Managing Member", "Date: July 1, 2025"]),
         Spacer(1, 18),
         two_sigs(["Attest:", "[signature on file]", "City Clerk"],
                  ["Approved as to form:", "[signature on file]", "City Attorney"]),
         Spacer(1, 18),
         para("Recorded with the Bayside County Recorder on July 8, 2025, as Document No. 2025-0187733.", SMALL),
         ],
    ]
    n_sr = build_record(out / f_sr, sr, "Staff report · Beacon Point · 2025-05-06")
    n_res = build_record(out / f_res, res, "Resolution No. 2025-41 · 2025-05-13")
    n_ag = build_record(out / f_ag, ag, "PILOT and regulatory agreement · Beacon Point · 2025-07-01")
    docs = [
        {"file": f_sr, "id": "staff-report", "type": "Staff report", "date": "2025-05-06",
         "title": "Staff report: Beacon Point payment in lieu of taxes request", "pages": n_sr, "signed_by": []},
        {"file": f_res, "id": "resolution", "type": "Council resolution", "date": "2025-05-13",
         "title": "Resolution No. 2025-41 concerning payments in lieu of taxes for the Beacon Point Apartments",
         "pages": n_res, "signed_by": []},
        {"file": f_ag, "id": "agreement", "type": "PILOT and regulatory agreement", "date": "2025-07-01",
         "title": "Payment in Lieu of Taxes and Regulatory Agreement, Beacon Point Apartments", "pages": n_ag,
         "signed_by": ["City of Lantern Bay", "Beacon Point Housing LLC"]},
    ]
    V = {"units": "16 of 80 homes", "income_basis": "60 percent of area median income",
         "rent_limits": "60 percent rent limit based on HUD income limits", "term": "30 years from first lease",
         "responsible_party": "Owner and any later owner", "reporting": "Annual certificate by March 1",
         "remedies": "Repay abated taxes with interest after 60-day cure period",
         "public_support": "15-year payment in lieu of taxes"}
    W = {"units_sr": "will reserve", "income_sr": "must be leased", "rent_sr": "may not exceed",
         "term_sr": "will last", "resp_sr": "is responsible", "report_sr": "will file", "remedy_sr": "must repay",
         "support_sr": "recommends", "support_res": "approves", "units_res": "are reserved",
         "income_res": "is leased", "rent_res": "do not exceed", "term_res": "last",
         "resp_res": "are responsible", "report_res": "files", "remedy_res": "repays",
         "support_ag": "shall pay", "units_ag": "shall reserve", "income_ag": "shall be leased",
         "rent_ag": "shall not exceed", "term_ag": "shall remain in effect", "resp_ag": "is responsible",
         "report_ag": "shall deliver", "notice_ag": "shall give", "remedy_ag": "shall repay"}
    term_of = {"units": "units", "income": "income_basis", "rent": "rent_limits", "term": "term",
               "resp": "responsible_party", "report": "reporting", "remedy": "remedies", "notice": "remedies",
               "support": "public_support"}
    where = {  # key -> (file, page, stage)
        "support_sr": (f_sr, 1, "supported"), "units_sr": (f_sr, 1, "proposed"), "income_sr": (f_sr, 1, "proposed"),
        "rent_sr": (f_sr, 2, "proposed"), "term_sr": (f_sr, 2, "proposed"), "resp_sr": (f_sr, 2, "proposed"),
        "report_sr": (f_sr, 2, "proposed"), "remedy_sr": (f_sr, 2, "proposed"),
        "support_res": (f_res, 1, "supported"), "units_res": (f_res, 1, "supported"),
        "income_res": (f_res, 1, "supported"), "rent_res": (f_res, 1, "supported"),
        "term_res": (f_res, 1, "supported"), "resp_res": (f_res, 2, "supported"),
        "report_res": (f_res, 2, "supported"), "remedy_res": (f_res, 2, "supported"),
        "support_ag": (f_ag, 1, "signed"), "units_ag": (f_ag, 2, "signed"), "income_ag": (f_ag, 2, "signed"),
        "rent_ag": (f_ag, 2, "signed"), "term_ag": (f_ag, 2, "signed"), "resp_ag": (f_ag, 2, "signed"),
        "report_ag": (f_ag, 3, "signed"), "notice_ag": (f_ag, 3, "signed"), "remedy_ag": (f_ag, 3, "signed"),
    }
    notes = {"notice_ag": "Default notice from the City.", "support_sr": "This is the public support being asked for.",
             "rent_sr": "Rent limit is tied to HUD income limits that change each year."}
    claims = []
    for i, (key, (file, page, stage)) in enumerate(where.items(), start=1):
        term = term_of[key.split("_")[0]]
        value = "Written notice of default" if key == "notice_ag" else V[term]
        claims.append(claim(f"b{i:02d}", term, BP[key], file, page, stage, W[key], value, notes.get(key, "")))
    gold = {"not_located": [], "differs": [],
            "story": "A complete deal. All seven terms appear in the staff report, the resolution and the "
                     "agreement signed by both the City and the owner, and they match."}
    return finish(out, "Beacon Point", "beacon-point", 80, "Beacon Point Housing LLC", docs, claims, gold)


# ---------------------------------------------------------------------------
# Deal 3: Mill Street (after signing: end date coming, a yearly check missing)
# ---------------------------------------------------------------------------
MS = {
    "support_ag": "By Resolution No. 2011-18, the City approved a 15-year partial property tax exemption for the Project.",
    "units_ag": "The Owner shall reserve 9 of the 60 homes in the Project as Affordable Homes.",
    "income_ag": "Each Affordable Home shall be leased to a household with income at or below 50 percent of Area Median Income.",
    "rent_ag": "Monthly rent for each Affordable Home shall not exceed 30 percent of 50 percent of Area Median Income, adjusted for household size.",
    "term_ag": "The Affordability Period begins on January 1, 2012 and ends on December 31, 2026.",
    "resp_ag": "The Owner is responsible for compliance with this Agreement, and this Agreement binds every later owner of the Project.",
    "report_ag": "The Owner shall deliver an annual compliance certificate to the City by March 31 of each year.",
    "remedy_ag": "If a default is not cured within 30 days after written notice from the City, the Owner shall repay the property taxes exempted during the period of default.",
    "report_c24": "This certificate is submitted under Section 7.1 of the Agreement for reporting year 2024.",
    "units_c24": "As of December 31, 2024, 9 of the 9 required Affordable Homes were leased to income-qualified households.",
    "income_c24": "All 9 households in Affordable Homes had incomes at or below 50 percent of Area Median Income when last certified.",
    "rent_c24": "No Affordable Home was charged rent above the limit in Section 4.3 during the reporting year.",
}
MS_OBS = {
    "missing": "The certificate for reporting year 2025 was due on March 31, 2026 and is marked not received.",
    "reminder": "A reminder notice was sent to the owner on April 2, 2026.",
    "ending": "Under Section 5.1 of the agreement, the affordability period ends on December 31, 2026.",
}


def mill_street() -> dict:
    out = OUT_DIR_CURRENT / "mill-street"
    out.mkdir(parents=True, exist_ok=True)
    f_ag, f_c24, f_memo = "01-regulatory-agreement-2011.pdf", "02-compliance-certificate-2024.pdf", "03-staff-memo-2026.pdf"

    ag = [
        [para("REGULATORY AGREEMENT", TITLE),
         para("Mill Street Lofts · 315 Mill Street, Lantern Bay", SUBTITLE),
         para("EXCERPT. Sections 1 through 3, 8 and 9 and the exhibits are omitted from this copy.", SMALL),
         Spacer(1, 4),
         para("This Regulatory Agreement (this \"Agreement\") is made as of June 14, 2011, between the City "
              "of Lantern Bay (the \"City\") and Mill Street Housing Associates LP (the \"Owner\")."),
         para("RECITALS", HEAD),
         para("A. The Owner owns a 60-home rental project at 315 Mill Street (the \"Project\")."),
         para(MS["support_ag"], BODY, "B."),
         para("C. The exemption is granted in exchange for the affordability terms in this Agreement."),
         para("SECTION 4. AFFORDABILITY", HEAD),
         para(MS["units_ag"], INDENT, "4.1"),
         para(MS["income_ag"], INDENT, "4.2"),
         ],
        [para(MS["rent_ag"], INDENT, "4.3"),
         para("SECTION 5. TERM", HEAD),
         para(MS["term_ag"], INDENT, "5.1"),
         para("Sections 4 and 7 end at the close of the Affordability Period. Section 10 survives for "
              "defaults that occur before that date.", INDENT, "5.2"),
         para("SECTION 6. RESPONSIBLE PARTY", HEAD),
         para(MS["resp_ag"], INDENT, "6.1"),
         para("SECTION 7. REPORTING", HEAD),
         para(MS["report_ag"], INDENT, "7.1"),
         para("The certificate shall report counts for the prior calendar year and shall not include "
              "household names.", INDENT, "7.2"),
         ],
        [para("SECTION 10. DEFAULT AND REMEDIES", HEAD),
         para(MS["remedy_ag"], INDENT, "10.1"),
         para("The City may also seek specific performance of this Agreement.", INDENT, "10.2"),
         para("SIGNATURES", HEAD),
         para("The parties have signed this Agreement as of the date first written above."),
         Spacer(1, 10),
         two_sigs(["CITY OF LANTERN BAY", "[signature on file]", "City Manager", "Date: June 14, 2011"],
                  ["MILL STREET HOUSING ASSOCIATES LP", "By its general partner", "[signature on file]",
                   "Authorized Officer", "Date: June 14, 2011"]),
         Spacer(1, 18),
         para("Recorded with the Bayside County Recorder on June 21, 2011, as Document No. 2011-0042519.", SMALL),
         ],
    ]
    c24 = [
        [*letterhead(*CITY_HCD),
         para("ANNUAL OWNER COMPLIANCE CERTIFICATE", TITLE),
         para("Reporting year 2024 (January 1 to December 31, 2024)", SUBTITLE),
         memo_table([("Project:", "Mill Street Lofts, 315 Mill Street"),
                     ("Owner:", "Mill Street Housing Associates LP"),
                     ("Agreement:", "Regulatory Agreement dated June 14, 2011"),
                     ("Due date:", "March 31, 2025")]),
         Spacer(1, 6),
         para("Part A. Basis", HEAD),
         para(MS["report_c24"]),
         para("Part B. Counts (no household information)", HEAD),
         grid_table([["Item", "Count"],
                     ["Homes in the Project", "60"],
                     ["Affordable Homes required (Section 4.1)", "9"],
                     ["Affordable Homes leased on December 31, 2024", "9"],
                     ["Affordable Homes vacant on December 31, 2024", "0"],
                     ["Income recertifications completed in 2024", "9"]], [4.6, 1.8]),
         Spacer(1, 8),
         para(MS["units_c24"]),
         para(MS["income_c24"]),
         para(MS["rent_c24"]),
         para("Part C. Certification", HEAD),
         para("The Owner certifies that the information in this certificate is true and complete."),
         two_sigs(["MILL STREET HOUSING ASSOCIATES LP", "[signature on file]", "Authorized Officer",
                   "Date: March 18, 2025"],
                  ["Received by the City:", "[signature on file]", "Housing Compliance Analyst",
                   "Date: March 20, 2025"]),
         ],
    ]
    memo = [
        [*letterhead(*CITY_HCD),
         para("MEMORANDUM", TITLE),
         memo_table([("To:", "Housing Director"), ("From:", "Housing Compliance Analyst"),
                     ("Date:", "April 15, 2026"),
                     ("Subject:", "Mill Street Lofts: annual certificates and end of the affordability period")]),
         HRFlowable(width="100%", thickness=0.5, color=RULE, spaceBefore=6, spaceAfter=10),
         para("1. Purpose", HEAD),
         para("This memo reports the status of the yearly owner certificates for Mill Street Lofts under the "
              "Regulatory Agreement dated June 14, 2011, and notes the upcoming end of the affordability period."),
         para("2. Annual certificates", HEAD),
         grid_table([["Reporting year", "Due", "Status", "Received"],
                     ["2021", "March 31, 2022", "Received", "March 29, 2022"],
                     ["2022", "March 31, 2023", "Received", "March 30, 2023"],
                     ["2023", "March 31, 2024", "Received", "April 3, 2024"],
                     ["2024", "March 31, 2025", "Received", "March 20, 2025"],
                     ["2025", "March 31, 2026", "Not received", "—"]], [1.3, 1.6, 1.6, 1.9]),
         Spacer(1, 8),
         para(MS_OBS["missing"]),
         para(MS_OBS["reminder"]),
         para("3. End of the affordability period", HEAD),
         para(MS_OBS["ending"]),
         para("No extension or new agreement was located in the City's files."),
         ],
        [para("4. Next steps", HEAD),
         para("Staff will send a second notice asking for the 2025 certificate by May 15, 2026.", INDENT, "(a)"),
         para("Staff will brief the Council before the affordability period ends, so the Council can "
              "consider its options.", INDENT, "(b)"),
         para("Staff will confirm whether the City's records show any sale of the Project since 2011.", INDENT, "(c)"),
         Spacer(1, 12),
         para("cc: City Attorney's Office", SIG),
         ],
    ]
    n_ag = build_record(out / f_ag, ag, "Regulatory agreement (excerpt) · Mill Street · 2011-06-14")
    n_c24 = build_record(out / f_c24, c24, "Compliance certificate · Mill Street · 2024")
    n_memo = build_record(out / f_memo, memo, "Staff memo · Mill Street · 2026-04-15")
    docs = [
        {"file": f_ag, "id": "agreement-2011", "type": "Regulatory agreement (excerpt)", "date": "2011-06-14",
         "title": "Regulatory Agreement, Mill Street Lofts (excerpt)", "pages": n_ag,
         "signed_by": ["City of Lantern Bay", "Mill Street Housing Associates LP"]},
        {"file": f_c24, "id": "certificate-2024", "type": "Annual compliance certificate", "date": "2025-03-20",
         "title": "Annual owner compliance certificate, reporting year 2024", "pages": n_c24,
         "signed_by": ["Mill Street Housing Associates LP"]},
        {"file": f_memo, "id": "staff-memo-2026", "type": "Staff memo", "date": "2026-04-15",
         "title": "Mill Street Lofts: annual certificates and end of the affordability period", "pages": n_memo,
         "signed_by": []},
    ]
    rows = [
        ("support_ag", "public_support", f_ag, 1, "signed", "approved", "15-year partial property tax exemption", ""),
        ("units_ag", "units", f_ag, 1, "signed", "shall reserve", "9 of 60 homes", ""),
        ("income_ag", "income_basis", f_ag, 1, "signed", "shall be leased", "50 percent of area median income", ""),
        ("rent_ag", "rent_limits", f_ag, 2, "signed", "shall not exceed", "30 percent of 50 percent of area median income", ""),
        ("term_ag", "term", f_ag, 2, "signed", "ends on", "15 years, January 1, 2012 to December 31, 2026",
         "The end date is less than two months after this sample was made."),
        ("resp_ag", "responsible_party", f_ag, 2, "signed", "is responsible", "Owner and any later owner", ""),
        ("report_ag", "reporting", f_ag, 2, "signed", "shall deliver", "Annual certificate by March 31", ""),
        ("remedy_ag", "remedies", f_ag, 3, "signed", "shall repay",
         "Repay exempted taxes after 30-day cure period", ""),
        ("report_c24", "reporting", f_c24, 1, "delivered", "is submitted", "2024 certificate received March 20, 2025",
         "Owner-reported counts. Not independently checked."),
        ("units_c24", "units", f_c24, 1, "delivered", "were leased", "9 of 9 affordable homes leased",
         "Owner-reported counts. Not independently checked."),
        ("income_c24", "income_basis", f_c24, 1, "delivered", "had incomes", "At or below 50 percent of area median income",
         "Owner-reported counts. Not independently checked."),
        ("rent_c24", "rent_limits", f_c24, 1, "delivered", "was charged", "No rent above the Section 4.3 limit",
         "Owner-reported counts. Not independently checked."),
    ]
    claims = [claim(f"m{i:02d}", t, MS[k], f, p, s, w, v, n) for i, (k, t, f, p, s, w, v, n) in enumerate(rows, 1)]
    gold = {
        "not_located": [], "differs": [],
        "observations": [
            {"id": "o01", "kind": "report_not_received", "term": "reporting", "quote": MS_OBS["missing"],
             "file": f_memo, "page": 1, "value": "2025 certificate not received"},
            {"id": "o02", "kind": "reminder_sent", "term": "reporting", "quote": MS_OBS["reminder"],
             "file": f_memo, "page": 1, "value": "Reminder sent April 2, 2026"},
            {"id": "o03", "kind": "term_ending", "term": "term", "quote": MS_OBS["ending"],
             "file": f_memo, "page": 1, "value": "2026-12-31"},
        ],
        "follow_up": {"term_ends": "2026-12-31", "reports_not_received": ["2025"]},
        "story": "Signed in 2011 for 15 years. The 2024 yearly certificate shows 9 of 9 homes leased. The 2025 "
                 "certificate is marked not received, and the affordability period ends on December 31, 2026.",
    }
    return finish(out, "Mill Street", "mill-street", 60, "Mill Street Housing Associates LP", docs, claims, gold)


# ---------------------------------------------------------------------------
def finish(out: Path, name, slug, homes, owner, docs, claims, gold) -> dict:
    located = {c["term"] for c in claims}
    missing = [t for t in TERMS if t not in located]
    if missing != gold["not_located"]:
        raise SystemExit(f"{slug}: not_located should be {missing}, not {gold['not_located']}")
    manifest = {"notice": NOTICE, "deal": name, "slug": slug, "city": "Lantern Bay", "county": "Bayside County",
                "homes": homes, "owner": owner, "documents": docs}
    expected = {"notice": NOTICE, "deal": name, "terms": TERMS, "stages": STAGES, **gold, "claims": claims}
    for fname, data in [("manifest.json", manifest), ("expected_claims.json", expected)]:
        (out / fname).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                 newline="\n")
    try:  # check each PDF has the planned page count (catches content spilling onto a new page)
        from pypdf import PdfReader
    except ImportError:
        return manifest
    for d in docs:
        actual = len(PdfReader(out / d["file"]).pages)
        if actual != d["pages"]:
            raise SystemExit(f"{slug}/{d['file']}: planned {d['pages']} pages but drew {actual}. Trim the text.")
    return manifest


OUT_DIR_CURRENT = OUT_DIR


def main(argv: list[str]) -> int:
    global OUT_DIR_CURRENT
    OUT_DIR_CURRENT = Path(argv[1]) if len(argv) > 1 else OUT_DIR
    for build in (harbor_walk, beacon_point, mill_street):
        m = build()
        print(f"{m['slug']}: " + ", ".join(f"{d['file']} ({d['pages']} p)" for d in m["documents"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

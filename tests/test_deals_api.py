import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import ai, deals, ledger, pipeline, storage
from app.main import app

SIGNED = ledger.load_packet()["documents"][-1]  # The developer's signed letter in the demo packet.


def letter_pdf() -> bytes:
    return deals.demo_pdf(SIGNED)


def stub_reading(pages):
    """What a well-behaved model might return for the demo letter, plus one made-up quote."""
    text = "\n".join(pages)
    quotes = [p for page in SIGNED["pages"] for p in page["paragraphs"]]
    units = next(q for q in quotes if "12" in q)
    candidates = [ai.PdfCandidate(topic="units", quote=units, page=1, wording="will", value="12 homes"),
                  ai.PdfCandidate(topic="remedies", quote="All 500 homes were delivered.", page=1, wording="were",
                                  value="500 homes")]
    line = next(q for q in quotes if q.startswith("Signed by"))
    sigs = [ai.Signature(party=name, quote=line, page=1) for name in SIGNED.get("signed_by", []) if name in text]
    reading = ai.PdfReading(document_type="letter", title="Letter", date=SIGNED["date"], draft=False,
                            signatures=sigs, candidates=candidates)
    return ai.ReadResult(mode="live", model="stub", reading=reading, tokens_in=1000, tokens_out=200, cost_usd=0.0008)


class DealApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        storage.set_store(storage.LocalStorage(Path(self.tmp.name) / "runtime"))
        self.addCleanup(storage.set_store, None)
        patcher = mock.patch.object(pipeline, "READINGS_DIR", Path(self.tmp.name) / "readings")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(deals, "run_inline", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(ai, "read_document", side_effect=stub_reading)
        self.reader = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def new_deal(self):
        r = self.client.post("/api/deals", json={"name": "Harbor Walk", "city": "Lantern Bay"})
        self.assertEqual(r.status_code, 201)
        return r.json()["id"]

    def upload(self, deal_id, data=None, **form):
        files = {"file": ("letter.pdf", data if data is not None else letter_pdf(), "application/pdf")}
        return self.client.post(f"/api/deals/{deal_id}/documents", files=files, data=form)

    def test_create_upload_and_review(self):
        deal_id = self.new_deal()
        r = self.upload(deal_id, type="Signed letter", date=SIGNED["date"])
        self.assertEqual(r.status_code, 202)
        doc = r.json()
        self.assertEqual(doc["status"], "done")
        self.assertEqual(doc["counts"]["kept"], 1)
        self.assertEqual(doc["counts"]["dropped"], 1)
        self.assertEqual((doc["stage"], doc["signed_by"]), ("signed", SIGNED["signed_by"]))
        detail = self.client.get(f"/api/deals/{deal_id}").json()
        self.assertEqual([d["id"] for d in detail["documents"]], [doc["id"]])
        review = self.client.get(f"/api/deals/{deal_id}/review").json()
        self.assertEqual(review["project"], "Harbor Walk")
        self.assertEqual([c["status"] for c in review["claims"]], ["signed"])
        self.assertTrue(all(c["quote_checked"] for c in review["claims"]))
        listing = self.client.get("/api/deals").json()
        row = next(r for r in listing if r["id"] == deal_id)
        self.assertEqual((row["documents"], row["claim_count"], row["furthest_status"]), (1, 1, "signed"))
        self.assertEqual(row["terms_not_located"], len(ledger.TERMS) - 1)
        self.assertEqual((row["documents"], row["furthest_status"]), (1, "signed"))

    def test_same_file_twice_uses_the_cached_reading(self):
        deal_id = self.new_deal()
        data = letter_pdf()
        self.upload(deal_id, data)
        second = self.upload(deal_id, data).json()
        self.assertEqual(self.reader.call_count, 1)
        self.assertTrue(second["from_cache"])

    def test_file_and_page_text(self):
        deal_id = self.new_deal()
        doc_id = self.upload(deal_id).json()["id"]
        r = self.client.get(f"/api/deals/{deal_id}/documents/{doc_id}/file")
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        page = self.client.get(f"/api/deals/{deal_id}/documents/{doc_id}/pages/1").json()
        self.assertIn("12", page["text"])
        self.assertEqual(self.client.get(f"/api/deals/{deal_id}/documents/{doc_id}/pages/9").status_code, 404)

    def test_bad_uploads_are_refused(self):
        deal_id = self.new_deal()
        self.assertEqual(self.upload(deal_id, data=b"hello").status_code, 422)
        self.assertEqual(self.upload(deal_id, date="March 3").status_code, 422)
        with mock.patch.object(pipeline, "MAX_PDF_PAGES", 0):
            r = self.upload(deal_id)
        self.assertEqual(r.status_code, 422)
        self.assertIn("pages", r.json()["detail"])
        with mock.patch.object(pipeline, "MAX_PDF_BYTES", 100):
            self.assertEqual(self.upload(deal_id).status_code, 413)
        self.assertEqual(self.client.get(f"/api/deals/{deal_id}").json()["documents"], [])
        self.assertEqual(self.client.post("/api/deals/nope/documents", files={"file": ("a.pdf", b"x")}).status_code, 404)

    def test_model_failure_marks_the_document_failed(self):
        deal_id = self.new_deal()
        self.reader.side_effect = lambda pages: ai.ReadResult(mode="failed", notice="Live reading did not finish.")
        doc = self.upload(deal_id).json()
        self.assertEqual((doc["status"], doc["error"]), ("failed", "Live reading did not finish."))
        review = self.client.get(f"/api/deals/{deal_id}/review").json()
        self.assertTrue(any(q["key"].startswith("failed-") for q in review["questions"]))

    def test_unknown_ids_are_404(self):
        self.assertEqual(self.client.get("/api/deals/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/deals/nope/review").status_code, 404)
        self.assertEqual(self.client.get("/api/deals/../x").status_code, 404)
        deal_id = self.new_deal()
        self.assertEqual(self.client.get(f"/api/deals/{deal_id}/documents/nope/file").status_code, 404)

    def test_export_xlsx_and_csv(self):
        from openpyxl import load_workbook

        deal_id = self.new_deal()
        self.upload(deal_id, type="Signed letter")
        r = self.client.get(f"/api/deals/{deal_id}/export.xlsx")
        self.assertIn("spreadsheetml", r.headers["content-type"])
        wb = load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ["Claims", "Terms", "Open questions", "Review log", "About"])
        rows = list(wb["Claims"].values)
        self.assertEqual(list(rows[0]), deals.CLAIM_COLUMNS)
        self.assertEqual(rows[1][0], "Units")
        self.assertEqual(rows[1][5], "Signed")
        self.assertEqual(len(list(wb["Terms"].values)), len(ledger.TERMS) + 1)
        text = self.client.get(f"/api/deals/{deal_id}/export.csv").content.decode("utf-8-sig")
        parsed = list(csv.reader(io.StringIO(text)))
        self.assertEqual(parsed[0], deals.CLAIM_COLUMNS)
        self.assertEqual(len(parsed), 2)

    def test_export_preview_matches_the_files(self):
        from openpyxl import load_workbook

        deal_id = self.new_deal()
        self.upload(deal_id, type="Signed letter")
        r = self.client.get(f"/api/deals/{deal_id}/export.json")
        self.assertEqual(r.status_code, 200)
        preview = r.json()
        self.assertEqual(preview["title"], "Harbor Walk · Promise receipt")
        self.assertEqual(preview["files"], {"xlsx": f"{deal_id}-promise-ledger.xlsx", "csv": f"{deal_id}-promise-ledger.csv"})
        self.assertEqual(preview["csv_sheet"], "Claims")
        wb = load_workbook(io.BytesIO(self.client.get(f"/api/deals/{deal_id}/export.xlsx").content))
        self.assertEqual([sheet["name"] for sheet in preview["sheets"]], wb.sheetnames)
        for sheet in preview["sheets"][:-1]:  # About carries the export time, so only its shape is compared.
            file_rows = [["" if v is None else v for v in row] for row in wb[sheet["name"]].values]  # Empty cells read back as None.
            self.assertEqual(file_rows[0], sheet["columns"])
            self.assertEqual(file_rows[1:], sheet["rows"])
        text = self.client.get(f"/api/deals/{deal_id}/export.csv").content.decode("utf-8-sig")
        claims = preview["sheets"][0]
        self.assertEqual(list(csv.reader(io.StringIO(text))), [claims["columns"]] + [[str(v) for v in row] for row in claims["rows"]])
        about = next(sheet for sheet in preview["sheets"] if sheet["name"] == "About")
        self.assertEqual(len(about["rows"]), wb["About"].max_row)

    def test_export_preview_needs_a_deal(self):
        self.assertEqual(self.client.get("/api/deals/nope/export.json").status_code, 404)

    def test_export_preview_keeps_formula_guard(self):
        review = {"project": "P", "city": "C", "notice": "n", "documents": [{"id": "d", "title": "=HYPERLINK(1)"}], "terms": [],
                  "claims": [{"topic": "units", "quote": "=1+1", "document": "d", "document_type": "Letter",
                              "date": "", "page": 1, "status": "proposed", "quote_checked": True}]}
        row = deals.export_preview(review, "p")["sheets"][0]["rows"][0]
        self.assertEqual(row[1], "'=1+1")
        self.assertEqual(row[2], "'=HYPERLINK(1)")

    def test_export_cells_cannot_run_formulas(self):
        review = {"documents": [{"id": "d", "title": "=HYPERLINK(1)"}], "terms": [],
                  "claims": [{"topic": "units", "quote": "=1+1", "document": "d", "document_type": "Letter",
                              "date": "", "page": 1, "status": "proposed", "quote_checked": True}]}
        row = next(csv.reader(io.StringIO(deals.export_csv(review).splitlines()[1])))
        self.assertEqual(row[1], "'=1+1")
        self.assertEqual(row[2], "'=HYPERLINK(1)")

    def test_share_link_is_read_only(self):
        deal_id = self.new_deal()
        self.upload(deal_id)
        share = self.client.post(f"/api/deals/{deal_id}/share").json()
        self.assertTrue(share["url"].endswith(f"/r/{share['token']}"))
        data = self.client.get(f"/api/share/{share['token']}").json()
        self.assertTrue(data["read_only"])
        self.assertEqual(data["summary"], self.client.get(f"/api/deals/{deal_id}/review").json()["summary"])
        html = self.client.get(f"/r/{share['token']}").text
        self.assertIn('"read_only": true', html)
        self.assertEqual(self.client.get("/r/not-a-real-token-at-all").status_code, 404)
        self.assertEqual(self.client.get("/api/r/x").status_code, 404)

    def test_reminders_endpoint(self):
        self.assertEqual(self.client.get("/api/reminders").json(), [])

    def test_seed_demo_when_no_samples(self):
        store = storage.get_store()
        seeded = deals.seed(store, samples_dir=Path(self.tmp.name) / "none")
        self.assertEqual(seeded, [deals.DEMO_DEAL_ID])
        review = self.client.get(f"/api/deals/{deals.DEMO_DEAL_ID}/review").json()
        demo = ledger.build_review()
        self.assertEqual(review["summary"]["sentences"], demo["summary"]["sentences"])
        self.assertTrue(all(c["verified"] for c in review["claims"]))
        self.assertEqual(deals.seed(store, samples_dir=Path(self.tmp.name) / "none"), [])  # Only on an empty store.


class FakeSnap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return json.loads(json.dumps(self._data))


class NotFound(Exception):
    code = 404


class FakeQuery:
    def __init__(self, snaps):
        self.snaps = snaps

    def stream(self):
        return self.snaps


class FakeDocRef:
    def __init__(self, tree, path):
        self.tree, self.path = tree, path

    def get(self):
        return FakeSnap(self.tree.get(self.path))

    def set(self, data):
        self.tree[self.path] = json.loads(json.dumps(data))

    def collection(self, name):
        return FakeCollection(self.tree, self.path + (name,))


class FakeCollection:
    def __init__(self, tree, path):
        self.tree, self.path = tree, path

    def document(self, doc_id):
        return FakeDocRef(self.tree, self.path + (doc_id,))

    def stream(self):
        n = len(self.path) + 1
        return [FakeSnap(v) for k, v in self.tree.items() if len(k) == n and k[:-1] == self.path]

    def where(self, field, op, value):
        assert op == "=="
        return FakeQuery([snap for snap in self.stream() if (snap.to_dict() or {}).get(field) == value])


class FakeFirestore:
    def __init__(self):
        self.tree = {}

    def collection(self, name):
        return FakeCollection(self.tree, (name,))


class FakeBlob:
    def __init__(self, files, key):
        self.files, self.key = files, key

    def upload_from_string(self, data, content_type=None):
        self.files[self.key] = (bytes(data), content_type)

    def exists(self):
        return self.key in self.files

    def download_as_bytes(self):
        if self.key not in self.files:
            raise NotFound(self.key)
        return self.files[self.key][0]


class FakeGcs:
    def __init__(self):
        self.files = {}
        self.bucket_name = None

    def bucket(self, name):
        self.bucket_name = name
        files = self.files
        return type("Bucket", (), {"blob": lambda _self, key: FakeBlob(files, key)})()


class GcpStorageTests(unittest.TestCase):
    def setUp(self):
        self.fs, self.gcs = FakeFirestore(), FakeGcs()
        self.store = storage.GcpStorage(self.fs, self.gcs, bucket="pl-files")

    def test_records_round_trip(self):
        self.assertEqual(self.gcs.bucket_name, "pl-files")
        deal = deals.create_deal("Beacon Point", "Lantern Bay", deal_id="beacon", store=self.store)
        self.assertEqual(self.store.get_deal("beacon"), deal)
        self.assertEqual(self.store.list_deals(), [deal])
        self.store.put_document("beacon", {"id": "d1", "status": "queued"})
        self.assertEqual(self.store.list_documents("beacon"), [{"id": "d1", "status": "queued"}])
        self.assertIn(("deals", "beacon", "documents", "d1"), self.fs.tree)
        self.assertIsNone(self.store.get_document("beacon", "d2"))
        self.store.put_share("tok", "beacon")
        self.assertEqual(self.store.get_share_record("tok")["deal_id"], "beacon")
        self.assertIsNone(self.store.get_share_record("nope"))

    def test_files_go_to_the_bucket(self):
        self.store.put_blob("deals/b/d1.pdf", b"%PDF-1.4", "application/pdf")
        self.assertEqual(self.gcs.files["deals/b/d1.pdf"], (b"%PDF-1.4", "application/pdf"))
        self.assertEqual(self.store.get_blob("deals/b/d1.pdf"), b"%PDF-1.4")
        self.assertIsNone(self.store.get_blob("deals/b/none.pdf"))

    def test_full_upload_on_gcp_storage(self):
        deal = deals.create_deal("Harbor Walk", "Lantern Bay", store=self.store)
        with mock.patch.object(ai, "read_document", side_effect=stub_reading), \
                mock.patch.object(pipeline, "READINGS_DIR", Path(tempfile.mkdtemp())):
            doc = deals.add_document(deal["id"], "letter.pdf", letter_pdf(), "Signed letter", store=self.store,
                                     process=False)
            done = deals.process_document(deal["id"], doc["id"], self.store)
        self.assertEqual(done["status"], "done")
        review = deals.deal_review(deal["id"], self.store)
        self.assertEqual(len(review["claims"]), 1)

    def test_needs_a_bucket(self):
        with mock.patch.dict(os.environ, {"GCS_BUCKET": ""}):
            with self.assertRaises(RuntimeError):
                storage.GcpStorage(self.fs, self.gcs, bucket=None)

    def test_store_is_picked_from_env(self):
        storage.set_store(None)
        self.addCleanup(storage.set_store, None)
        with mock.patch.dict(os.environ, {"STORAGE": "local"}):
            self.assertIsInstance(storage.get_store(), storage.LocalStorage)

    def test_keys_cannot_escape(self):
        with self.assertRaises(ValueError):
            self.store.get_deal("../x")
        with self.assertRaises(ValueError):
            storage.LocalStorage(Path(tempfile.mkdtemp())).put_blob("deals/../../x", b"", "x")


if __name__ == "__main__":
    unittest.main()

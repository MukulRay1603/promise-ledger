"""Sample deals refresh themselves when their files, prompt or pipeline change, and only then."""
import itertools
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import ai, deals, storage

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


# ---------------------------------------------------------------------------
# Fake Firestore and Cloud Storage with the behaviour the lock relies on:
# create() fails if the document exists, and delete() can require an unchanged update time.

class AlreadyExists(Exception):
    code = 409


class NotFound(Exception):
    code = 404


class PreconditionFailed(Exception):
    code = 412


_clock = itertools.count(1)


class Snap:
    def __init__(self, ref, record):
        self.reference = ref
        self.exists = record is not None
        self._data = record["data"] if record else None
        self.update_time = record["t"] if record else None

    def to_dict(self):
        return json.loads(json.dumps(self._data)) if self._data is not None else None


class DocRef:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def get(self):
        return Snap(self, self.db.tree.get(self.path))

    def set(self, data):
        self.db.tree[self.path] = {"data": json.loads(json.dumps(data)), "t": next(_clock)}

    def create(self, data):
        if self.path in self.db.tree:
            raise AlreadyExists(self.path)
        self.set(data)

    def delete(self, option=None):
        record = self.db.tree.get(self.path)
        if option is not None and (record is None or record["t"] != option):
            raise PreconditionFailed(self.path)
        self.db.tree.pop(self.path, None)

    def collection(self, name):
        return Collection(self.db, self.path + (name,))


class Collection:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def document(self, doc_id):
        return DocRef(self.db, self.path + (doc_id,))

    def stream(self):
        n = len(self.path) + 1
        return [Snap(DocRef(self.db, k), v) for k, v in list(self.db.tree.items()) if len(k) == n and k[:-1] == self.path]

    def where(self, field, op, value):
        assert op == "=="
        snaps = [snap for snap in self.stream() if (snap.to_dict() or {}).get(field) == value]
        return type("Query", (), {"stream": lambda _self: snaps})()


class Firestore:
    def __init__(self):
        self.tree = {}

    def collection(self, name):
        return Collection(self, (name,))

    def write_option(self, last_update_time=None):
        return last_update_time


class Blob:
    def __init__(self, files, key):
        self.files, self.name = files, key

    def upload_from_string(self, data, content_type=None):
        self.files[self.name] = bytes(data)

    def exists(self):
        return self.name in self.files

    def download_as_bytes(self):
        if self.name not in self.files:
            raise NotFound(self.name)
        return self.files[self.name]

    def delete(self):
        self.files.pop(self.name, None)


class Bucket:
    def __init__(self, files):
        self.files = files

    def blob(self, key):
        return Blob(self.files, key)

    def list_blobs(self, prefix=""):
        return [Blob(self.files, k) for k in list(self.files) if k.startswith(prefix)]


class Gcs:
    def __init__(self):
        self.files = {}

    def bucket(self, name):
        return Bucket(self.files)


# ---------------------------------------------------------------------------

def no_model(pages):
    raise AssertionError("the model must not be called when cached readings match")


@unittest.skipUnless((SAMPLES / "harbor-walk" / "manifest.json").exists(), "sample deals not present")
class RefreshBehaviour:
    """Shared tests; subclasses supply make_store()."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.samples = Path(self.tmp.name) / "samples"
        shutil.copytree(SAMPLES, self.samples)
        self.store = self.make_store()
        for patcher in (mock.patch.object(ai, "read_document", side_effect=no_model),
                        mock.patch.object(deals, "run_inline", True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def refresh(self, **kw):
        return deals.refresh_samples(self.store, self.samples, **kw)

    def doc_ids(self, deal_id):
        return sorted(d["id"] for d in self.store.list_documents(deal_id))

    def test_first_start_seeds_every_sample_complete(self):
        self.assertEqual(sorted(self.refresh()), ["beacon-point", "harbor-walk", "mill-street"])
        for slug in ("beacon-point", "harbor-walk", "mill-street"):
            deal = self.store.get_deal(slug)
            self.assertEqual(deal["sample_slug"], slug)
            self.assertTrue(deal["sample_version"])
            docs = self.store.list_documents(slug)
            self.assertTrue(docs)
            self.assertTrue(all(d["status"] == "done" and d["from_cache"] for d in docs))

    def test_second_start_does_nothing(self):
        self.refresh()
        before = {s: self.doc_ids(s) for s in ("beacon-point", "harbor-walk", "mill-street")}
        with mock.patch.object(self.store, "delete_deal", side_effect=AssertionError("no deletes")), \
                mock.patch.object(self.store, "acquire_lock", side_effect=AssertionError("no lock needed")):
            self.assertEqual(self.refresh(), [])
        self.assertEqual(before, {s: self.doc_ids(s) for s in before})

    def test_deal_from_the_old_pipeline_is_replaced(self):
        self.refresh()
        old = self.store.get_deal("harbor-walk")
        for key in ("sample_slug", "sample_version", "as_of"):
            old.pop(key, None)
        self.store.put_deal(old)  # As seeded by v1: id is the slug, no version.
        stale = {"id": "dstale001", "filename": "old.pdf", "status": "done", "claims": [{"id": "x"}],
                 "file_key": "deals/harbor-walk/dstale001.pdf"}
        self.store.put_document("harbor-walk", stale)
        self.store.put_blob(stale["file_key"], b"%PDF old", "application/pdf")
        self.assertEqual(self.refresh(), ["harbor-walk"])
        self.assertNotIn("dstale001", self.doc_ids("harbor-walk"))
        self.assertIsNone(self.store.get_blob(stale["file_key"]))
        self.assertEqual(self.store.get_deal("harbor-walk")["as_of"], "2025-09-15")
        self.assertEqual(self.refresh(), [])

    def test_changed_manifest_refreshes_only_that_deal(self):
        self.refresh()
        beacon_docs = self.doc_ids("beacon-point")
        path = self.samples / "mill-street" / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["as_of"] = "2026-05-01"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.assertEqual(self.refresh(), ["mill-street"])
        self.assertEqual(self.store.get_deal("mill-street")["as_of"], "2026-05-01")
        self.assertEqual(self.doc_ids("beacon-point"), beacon_docs)

    def test_new_prompt_version_refreshes_all(self):
        self.refresh()
        with mock.patch("app.pipeline.PROMPT_ID", "changed1"):
            # The cache is keyed by prompt version too, so no reading is found: documents queue for the model.
            with mock.patch.object(ai, "read_document",
                                   return_value=ai.ReadResult(mode="off", notice="Live reading is off.")):
                self.assertEqual(len(self.refresh()), 3)

    def test_other_deals_are_never_touched(self):
        mine = deals.create_deal("Harbor Walk", "Lantern Bay", store=self.store)  # Gets a random suffix.
        self.store.put_document(mine["id"], {"id": "d1", "status": "done", "claims": []})
        squatter = {"id": "mill-street", "name": "Someone else's", "city": "X", "sample_slug": "other-sample"}
        self.store.put_deal(squatter)
        refreshed = self.refresh()
        self.assertNotIn("mill-street", refreshed)
        self.assertEqual(self.store.get_deal("mill-street")["name"], "Someone else's")
        self.assertEqual(self.doc_ids(mine["id"]), ["d1"])

    def test_another_instance_holding_the_lock_skips(self):
        self.assertTrue(self.store.acquire_lock(deals.REFRESH_LOCK, "instance-b", 600))
        self.assertEqual(self.refresh(owner="instance-a"), [])
        self.assertIsNone(self.store.get_deal("harbor-walk"))
        self.store.release_lock(deals.REFRESH_LOCK, "instance-b")
        self.assertEqual(len(self.refresh(owner="instance-a")), 3)

    def test_lock_is_exclusive_and_expires(self):
        self.assertTrue(self.store.acquire_lock("t", "a", 600))
        self.assertFalse(self.store.acquire_lock("t", "b", 600))
        self.store.release_lock("t", "b")  # Not the owner: no effect.
        self.assertFalse(self.store.acquire_lock("t", "b", 600))
        with mock.patch("app.storage.time.time", return_value=time.time() + 601):
            self.assertTrue(self.store.acquire_lock("t", "b", 600))  # Abandoned lock taken over.
        self.store.release_lock("t", "b")
        self.assertTrue(self.store.acquire_lock("t", "a", 600))


class LocalRefresh(RefreshBehaviour, unittest.TestCase):
    def make_store(self):
        return storage.LocalStorage(Path(self.tmp.name) / "runtime")


class GcpRefresh(RefreshBehaviour, unittest.TestCase):
    def make_store(self):
        self.db = Firestore()
        return storage.GcpStorage(self.db, Gcs(), bucket="pl-files")

    def test_stale_lock_is_only_removed_if_unchanged(self):
        store = self.store
        self.assertTrue(store.acquire_lock("t", "a", 600))
        ref = self.db.collection("locks").document("t")
        snap = ref.get()
        ref.set({"owner": "a", "at": time.time()})  # Refreshed after we read it.
        with self.assertRaises(PreconditionFailed):
            ref.delete(option=self.db.write_option(last_update_time=snap.update_time))
        with mock.patch("app.storage.time.time", return_value=time.time() + 601), \
                mock.patch.object(DocRef, "delete", side_effect=PreconditionFailed("raced")):
            self.assertFalse(store.acquire_lock("t", "b", 600))


class SeedEntryPoint(unittest.TestCase):
    def test_startup_seed_uses_refresh_when_samples_exist(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deals, "refresh_samples", return_value=["x"]) as r:
            store = storage.LocalStorage(Path(tmp))
            self.assertEqual(deals.seed(store, SAMPLES), ["x"])
            r.assert_called_once()


if __name__ == "__main__":
    unittest.main()

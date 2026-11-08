"""Where deals, documents, claims, share links and PDF files are kept.

Pick the backend with STORAGE=local (default) or STORAGE=gcp.
- local: JSON records and files under data/runtime/ (gitignored)
- gcp: Firestore (Native) for records, a Cloud Storage bucket (GCS_BUCKET) for files

Records are plain dicts. A document record carries its own verified claims, so
re-reading one document replaces only that document's claims.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(os.getenv("RUNTIME_DIR") or ROOT / "data" / "runtime")


class Storage(Protocol):
    def list_deals(self) -> list[dict]: ...
    def get_deal(self, deal_id: str) -> dict | None: ...
    def put_deal(self, deal: dict) -> None: ...
    def list_documents(self, deal_id: str) -> list[dict]: ...
    def get_document(self, deal_id: str, doc_id: str) -> dict | None: ...
    def put_document(self, deal_id: str, doc: dict) -> None: ...
    def put_share(self, token: str, deal_id: str) -> None: ...
    def get_share(self, token: str) -> str | None: ...
    def put_blob(self, key: str, data: bytes, content_type: str) -> None: ...
    def get_blob(self, key: str) -> bytes | None: ...


def _safe(part: str) -> str:
    if not part or any(c in part for c in "/\\:") or part.startswith("."):
        raise ValueError(f"bad storage key part {part!r}")
    return part


class LocalStorage:
    """JSON files on disk. One lock keeps background workers from interleaving writes."""

    def __init__(self, root: Path = RUNTIME_DIR):
        self.root = Path(root)
        self._lock = threading.RLock()

    def _read(self, path: Path) -> dict | None:
        # Reads take the lock too: on Windows, replacing a file another thread has open fails.
        with self._lock:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None

    def _write(self, path: Path, record: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
        with self._lock:
            tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            for attempt in range(5):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:  # An outside reader (antivirus, indexer) can hold the file briefly.
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))

    def _deal_dir(self, deal_id: str) -> Path:
        return self.root / "deals" / _safe(deal_id)

    def list_deals(self) -> list[dict]:
        base = self.root / "deals"
        if not base.exists():
            return []
        deals = [self._read(d / "deal.json") for d in base.iterdir() if d.is_dir()]
        return [d for d in deals if d]

    def get_deal(self, deal_id: str) -> dict | None:
        return self._read(self._deal_dir(deal_id) / "deal.json")

    def put_deal(self, deal: dict) -> None:
        self._write(self._deal_dir(deal["id"]) / "deal.json", deal)

    def list_documents(self, deal_id: str) -> list[dict]:
        base = self._deal_dir(deal_id) / "documents"
        if not base.exists():
            return []
        docs = [self._read(p) for p in base.glob("*.json")]
        return [d for d in docs if d]

    def get_document(self, deal_id: str, doc_id: str) -> dict | None:
        return self._read(self._deal_dir(deal_id) / "documents" / f"{_safe(doc_id)}.json")

    def put_document(self, deal_id: str, doc: dict) -> None:
        self._write(self._deal_dir(deal_id) / "documents" / f"{_safe(doc['id'])}.json", doc)

    def put_share(self, token: str, deal_id: str) -> None:
        self._write(self.root / "shares" / f"{_safe(token)}.json", {"token": token, "deal_id": deal_id})

    def get_share(self, token: str) -> str | None:
        record = self._read(self.root / "shares" / f"{_safe(token)}.json")
        return record["deal_id"] if record else None

    def _blob_path(self, key: str) -> Path:
        return self.root.joinpath("files", *[_safe(p) for p in key.split("/")])

    def put_blob(self, key: str, data: bytes, content_type: str) -> None:
        path = self._blob_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_blob(self, key: str) -> bytes | None:
        try:
            return self._blob_path(key).read_bytes()
        except FileNotFoundError:
            return None


class GcpStorage:
    """Firestore collections: deals/{id}, deals/{id}/documents/{doc_id}, shares/{token}. Files in GCS."""

    def __init__(self, firestore_client=None, storage_client=None, bucket: str | None = None):
        if firestore_client is None:
            from google.cloud import firestore
            firestore_client = firestore.Client(database=os.getenv("FIRESTORE_DATABASE") or "(default)")
        if storage_client is None:
            from google.cloud import storage
            storage_client = storage.Client()
        bucket = bucket or os.getenv("GCS_BUCKET")
        if not bucket:
            raise RuntimeError("STORAGE=gcp needs GCS_BUCKET")
        self.db = firestore_client
        self.bucket = storage_client.bucket(bucket)

    def _deals(self):
        return self.db.collection("deals")

    def _docs(self, deal_id: str):
        return self._deals().document(_safe(deal_id)).collection("documents")

    def list_deals(self) -> list[dict]:
        return [snap.to_dict() for snap in self._deals().stream()]

    def get_deal(self, deal_id: str) -> dict | None:
        snap = self._deals().document(_safe(deal_id)).get()
        return snap.to_dict() if snap.exists else None

    def put_deal(self, deal: dict) -> None:
        self._deals().document(_safe(deal["id"])).set(deal)

    def list_documents(self, deal_id: str) -> list[dict]:
        return [snap.to_dict() for snap in self._docs(deal_id).stream()]

    def get_document(self, deal_id: str, doc_id: str) -> dict | None:
        snap = self._docs(deal_id).document(_safe(doc_id)).get()
        return snap.to_dict() if snap.exists else None

    def put_document(self, deal_id: str, doc: dict) -> None:
        self._docs(deal_id).document(_safe(doc["id"])).set(doc)

    def put_share(self, token: str, deal_id: str) -> None:
        self.db.collection("shares").document(_safe(token)).set({"token": token, "deal_id": deal_id})

    def get_share(self, token: str) -> str | None:
        snap = self.db.collection("shares").document(_safe(token)).get()
        return snap.to_dict()["deal_id"] if snap.exists else None

    def put_blob(self, key: str, data: bytes, content_type: str) -> None:
        self.bucket.blob(key).upload_from_string(data, content_type=content_type)

    def get_blob(self, key: str) -> bytes | None:
        blob = self.bucket.blob(key)
        if not blob.exists():
            return None
        return blob.download_as_bytes()


_store: Storage | None = None


def get_store() -> Storage:
    global _store
    if _store is None:
        kind = (os.getenv("STORAGE") or "local").lower()
        _store = GcpStorage() if kind == "gcp" else LocalStorage()
    return _store


def set_store(store: Storage | None) -> None:
    """Swap the backend (tests use a temporary LocalStorage)."""
    global _store
    _store = store

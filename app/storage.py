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
import shutil
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
    def put_share(self, token: str, deal_id: str, session: str | None = None) -> None: ...
    def get_share_record(self, token: str) -> dict | None: ...
    def list_decisions(self, deal_id: str) -> list[dict]: ...
    def put_decision(self, deal_id: str, event: dict) -> None: ...
    def get_share(self, token: str) -> str | None: ...
    def put_blob(self, key: str, data: bytes, content_type: str) -> None: ...
    def get_blob(self, key: str) -> bytes | None: ...
    def delete_deal(self, deal_id: str) -> None: ...
    def delete_document(self, deal_id: str, doc_id: str) -> None: ...
    def acquire_lock(self, name: str, owner: str, ttl_seconds: int) -> bool: ...
    def release_lock(self, name: str, owner: str) -> None: ...


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

    def put_share(self, token: str, deal_id: str, session: str | None = None) -> None:
        self._write(self.root / "shares" / f"{_safe(token)}.json", {"token": token, "deal_id": deal_id, "session": session})

    def get_share_record(self, token: str) -> dict | None:
        return self._read(self.root / "shares" / f"{_safe(token)}.json")

    def list_decisions(self, deal_id: str) -> list[dict]:
        base = self._deal_dir(deal_id) / "decisions"
        if not base.exists():
            return []
        events = [self._read(p) for p in base.glob("*.json")]
        return [e for e in events if e]

    def put_decision(self, deal_id: str, event: dict) -> None:
        self._write(self._deal_dir(deal_id) / "decisions" / f"{_safe(event['id'])}.json", event)

    def get_share(self, token: str) -> str | None:
        record = self.get_share_record(token)
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

    def delete_deal(self, deal_id: str) -> None:
        """Remove the deal, its documents and claims, and its files. Share links stay and resolve if it returns."""
        with self._lock:
            shutil.rmtree(self._deal_dir(deal_id), ignore_errors=True)
            shutil.rmtree(self.root / "files" / "deals" / _safe(deal_id), ignore_errors=True)

    def delete_document(self, deal_id: str, doc_id: str) -> None:
        """Remove one document, its claims and its files (deals/{id}/{doc}.pdf and .pages.json)."""
        with self._lock:
            (self._deal_dir(deal_id) / "documents" / f"{_safe(doc_id)}.json").unlink(missing_ok=True)
            folder = self.root / "files" / "deals" / _safe(deal_id)
            if folder.exists():
                for path in folder.glob(f"{_safe(doc_id)}.*"):
                    path.unlink(missing_ok=True)

    def acquire_lock(self, name: str, owner: str, ttl_seconds: int) -> bool:
        """Create a lock file atomically. A lock older than ttl_seconds is treated as abandoned."""
        path = self.root / "locks" / f"{_safe(name)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                held = self._read(path) or {}
                if time.time() - float(held.get("at", 0)) < ttl_seconds:
                    return False
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"owner": owner, "at": time.time()}, fh)
            return True
        return False

    def release_lock(self, name: str, owner: str) -> None:
        path = self.root / "locks" / f"{_safe(name)}.json"
        held = self._read(path)
        if held and held.get("owner") == owner:
            path.unlink(missing_ok=True)


def _already_exists(err: Exception) -> bool:
    """google.api_core.exceptions.AlreadyExists is a 409 Conflict."""
    return type(err).__name__ in ("AlreadyExists", "Conflict") or getattr(err, "code", None) == 409


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

    def put_share(self, token: str, deal_id: str, session: str | None = None) -> None:
        self.db.collection("shares").document(_safe(token)).set({"token": token, "deal_id": deal_id, "session": session})

    def get_share_record(self, token: str) -> dict | None:
        snap = self.db.collection("shares").document(_safe(token)).get()
        return snap.to_dict() if snap.exists else None

    def _decisions(self, deal_id: str):
        return self._deals().document(_safe(deal_id)).collection("decisions")

    def list_decisions(self, deal_id: str) -> list[dict]:
        return [snap.to_dict() for snap in self._decisions(deal_id).stream()]

    def put_decision(self, deal_id: str, event: dict) -> None:
        self._decisions(deal_id).document(_safe(event["id"])).set(event)

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

    def delete_deal(self, deal_id: str) -> None:
        """Remove the deal, its documents (claims live on them) and its files under deals/{id}/."""
        for snap in self._docs(deal_id).stream():
            snap.reference.delete()
        for snap in self._decisions(deal_id).stream():
            snap.reference.delete()
        self._deals().document(_safe(deal_id)).delete()
        for blob in self.bucket.list_blobs(prefix=f"deals/{_safe(deal_id)}/"):
            blob.delete()

    def delete_document(self, deal_id: str, doc_id: str) -> None:
        """Remove one document, its claims and its files (deals/{id}/{doc}.pdf and .pages.json)."""
        self._docs(deal_id).document(_safe(doc_id)).delete()
        for blob in self.bucket.list_blobs(prefix=f"deals/{_safe(deal_id)}/{_safe(doc_id)}."):
            blob.delete()

    def acquire_lock(self, name: str, owner: str, ttl_seconds: int) -> bool:
        """Take locks/{name} with an atomic create. Two instances cannot both succeed.

        An abandoned lock (older than ttl_seconds) is removed only if it has not changed since it was read
        (a last-update precondition), then the create is tried once more.
        """
        ref = self.db.collection("locks").document(_safe(name))
        for _ in range(2):
            try:
                ref.create({"owner": owner, "at": time.time()})
                return True
            except Exception as err:
                if not _already_exists(err):
                    raise
            snap = ref.get()
            if not snap.exists:
                continue
            if time.time() - float((snap.to_dict() or {}).get("at", 0)) < ttl_seconds:
                return False
            try:
                ref.delete(option=self.db.write_option(last_update_time=snap.update_time))
            except Exception:  # Someone else took or refreshed it first.
                return False
        return False

    def release_lock(self, name: str, owner: str) -> None:
        ref = self.db.collection("locks").document(_safe(name))
        snap = ref.get()
        if snap.exists and (snap.to_dict() or {}).get("owner") == owner:
            ref.delete(option=self.db.write_option(last_update_time=snap.update_time))


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

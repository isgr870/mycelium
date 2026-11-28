#!/usr/bin/env python3
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


DEFAULT_CHUNK_SIZE = 262144  # 256 KiB
DEFAULT_MAX_BLOB_BYTES = 256 * 1024 * 1024  # 256 MiB


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class ChunkStore:
    root_dir: str
    chunk_size: int = DEFAULT_CHUNK_SIZE
    max_bytes: int = DEFAULT_MAX_BLOB_BYTES
    _pinned: Set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root_dir)
        self.chunks_dir = self.root / "chunks"
        self.manifests_dir = self.root / "manifests"
        self.pins_file = self.root / "pinned_chunks.json"
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        self._load_pins()

    def _load_pins(self) -> None:
        if self.pins_file.is_file():
            try:
                data = json.loads(self.pins_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._pinned = {str(x).lower().strip() for x in data if x}
            except Exception:
                self._pinned = set()

    def _save_pins(self) -> None:
        tmp = self.pins_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(self._pinned), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.pins_file)

    def pin_chunk(self, chunk_hash: str) -> bool:
        h = chunk_hash.lower().strip()
        if not self.has_chunk(h):
            return False
        self._pinned.add(h)
        self._save_pins()
        return True

    def unpin_chunk(self, chunk_hash: str) -> bool:
        h = chunk_hash.lower().strip()
        existed = h in self._pinned
        self._pinned.discard(h)
        self._save_pins()
        return existed

    def is_pinned(self, chunk_hash: str) -> bool:
        return chunk_hash.lower().strip() in self._pinned

    def pin_manifest(self, manifest: dict) -> List[str]:
        pinned_now: List[str] = []
        for ch in manifest.get("chunks", []):
            h = str(ch).lower().strip()
            self._pinned.add(h)
            if self.has_chunk(h):
                pinned_now.append(h)
        self._save_pins()
        return pinned_now

    def _chunk_path(self, chunk_hash: str) -> Path:
        h = chunk_hash.lower().strip()
        return self.chunks_dir / h[:2] / h[2:4] / f"{h}.bin"

    def _manifest_path(self, manifest_hash: str) -> Path:
        h = manifest_hash.lower().strip()
        return self.manifests_dir / f"{h}.json"

    def _iter_chunk_files(self) -> List[tuple[str, Path, int, float]]:
        items: List[tuple[str, Path, int, float]] = []
        for p in self.chunks_dir.rglob("*.bin"):
            if not p.is_file():
                continue
            st = p.stat()
            ch_hash = p.stem.lower()
            score_ts = min(st.st_mtime, st.st_atime)
            items.append((ch_hash, p, int(st.st_size), float(score_ts)))
        return items

    def disk_usage_bytes(self) -> int:
        return sum(sz for _, _, sz, _ in self._iter_chunk_files())

    def evict_to_budget(self, target_bytes: Optional[int] = None) -> List[str]:
        budget = self.max_bytes if target_bytes is None else int(target_bytes)
        if budget < 0:
            budget = 0
        entries = self._iter_chunk_files()
        total = sum(sz for _, _, sz, _ in entries)
        if total <= budget:
            return []

        # Evict oldest unpinned chunks first
        candidates = [
            (ch_hash, path, sz, ts)
            for (ch_hash, path, sz, ts) in entries
            if ch_hash not in self._pinned
        ]
        candidates.sort(key=lambda item: item[3])

        evicted: List[str] = []
        for ch_hash, path, sz, _ in candidates:
            if total <= budget:
                break
            try:
                path.unlink(missing_ok=True)
                self._pinned.discard(ch_hash)
                total -= sz
                evicted.append(ch_hash)
            except OSError:
                continue

        if evicted:
            self._save_pins()
        return evicted

    def has_chunk(self, chunk_hash: str) -> bool:
        p = self._chunk_path(chunk_hash)
        return p.is_file()

    def get_chunk(self, chunk_hash: str) -> Optional[bytes]:
        p = self._chunk_path(chunk_hash)
        if not p.is_file():
            return None
        data = p.read_bytes()
        if sha256_hex(data) != chunk_hash.lower():
            raise ValueError(f"Corrupt local chunk on disk: {chunk_hash}")
        try:
            now = time.time()
            os.utime(p, (now, now))
        except OSError:
            pass
        return data

    def put_chunk(
        self,
        data: bytes,
        expected_hash: Optional[str] = None,
        pinned: bool = False,
        enforce_budget: bool = True,
    ) -> str:
        digest = sha256_hex(data)
        if expected_hash and digest != expected_hash.lower():
            raise ValueError(f"Chunk hash mismatch: expected {expected_hash}, got {digest}")
        p = self._chunk_path(digest)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
        if pinned:
            self._pinned.add(digest)
            self._save_pins()
        if enforce_budget and self.max_bytes > 0:
            self.evict_to_budget(self.max_bytes)
        return digest

    def build_manifest_from_bytes(
        self,
        data: bytes,
        filename: str = "blob.bin",
        pinned: bool = False,
    ) -> dict:
        chunk_hashes: List[str] = []
        for offset in range(0, len(data), self.chunk_size):
            piece = data[offset : offset + self.chunk_size]
            chunk_hashes.append(self.put_chunk(piece, pinned=pinned, enforce_budget=False))

        if self.max_bytes > 0:
            self.evict_to_budget(self.max_bytes)

        body = {
            "version": 1,
            "filename": filename,
            "total_size": len(data),
            "chunk_size": self.chunk_size,
            "chunk_count": len(chunk_hashes),
            "chunks": chunk_hashes,
        }
        canonical = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        manifest_hash = sha256_hex(canonical)
        manifest = {"manifest_hash": manifest_hash, **body}
        self._manifest_path(manifest_hash).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    def store_file(self, src_path: str, filename: Optional[str] = None, pinned: bool = False) -> dict:
        src = Path(src_path)
        raw = src.read_bytes()
        return self.build_manifest_from_bytes(raw, filename=filename or src.name, pinned=pinned)

    def load_manifest(self, manifest_hash: str) -> Optional[dict]:
        p = self._manifest_path(manifest_hash)
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def save_manifest(self, manifest: dict) -> str:
        mhash = manifest["manifest_hash"]
        self._manifest_path(mhash).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return mhash

    def missing_chunks(self, manifest: dict) -> List[str]:
        return [ch for ch in manifest.get("chunks", []) if not self.has_chunk(ch)]

    def reassemble_bytes(self, manifest: dict) -> bytes:
        pieces: List[bytes] = []
        for ch in manifest.get("chunks", []):
            piece = self.get_chunk(ch)
            if piece is None:
                raise FileNotFoundError(f"Missing chunk {ch} for manifest {manifest.get('manifest_hash')}")
            pieces.append(piece)
        assembled = b"".join(pieces)
        if len(assembled) != int(manifest.get("total_size", len(assembled))):
            raise ValueError("Assembled size mismatch")
        return assembled

    def reassemble_to_file(self, manifest: dict, out_path: str) -> Path:
        data = self.reassemble_bytes(manifest)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return out

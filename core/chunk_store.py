#!/usr/bin/env python3
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


DEFAULT_CHUNK_SIZE = 262144  # 256 KiB


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class ChunkStore:
    root_dir: str
    chunk_size: int = DEFAULT_CHUNK_SIZE

    def __post_init__(self) -> None:
        self.root = Path(self.root_dir)
        self.chunks_dir = self.root / "chunks"
        self.manifests_dir = self.root / "manifests"
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

    def _chunk_path(self, chunk_hash: str) -> Path:
        h = chunk_hash.lower().strip()
        return self.chunks_dir / h[:2] / h[2:4] / f"{h}.bin"

    def _manifest_path(self, manifest_hash: str) -> Path:
        h = manifest_hash.lower().strip()
        return self.manifests_dir / f"{h}.json"

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
        return data

    def put_chunk(self, data: bytes, expected_hash: Optional[str] = None) -> str:
        digest = sha256_hex(data)
        if expected_hash and digest != expected_hash.lower():
            raise ValueError(f"Chunk hash mismatch: expected {expected_hash}, got {digest}")
        p = self._chunk_path(digest)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
        return digest

    def build_manifest_from_bytes(self, data: bytes, filename: str = "blob.bin") -> dict:
        chunk_hashes: List[str] = []
        for offset in range(0, len(data), self.chunk_size):
            piece = data[offset : offset + self.chunk_size]
            chunk_hashes.append(self.put_chunk(piece))

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

    def store_file(self, src_path: str, filename: Optional[str] = None) -> dict:
        src = Path(src_path)
        raw = src.read_bytes()
        return self.build_manifest_from_bytes(raw, filename=filename or src.name)

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

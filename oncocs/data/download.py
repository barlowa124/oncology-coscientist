"""Download cohort archive and record a SHA-256 manifest."""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import requests

from oncocs.config import CohortConfig, DEFAULT_ROOT


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_cohort(cfg: CohortConfig, root: Path | str = DEFAULT_ROOT) -> dict:
    """Fetch the cohort archive, extract it under data/<cohort>/raw/, write manifest.json."""
    root = Path(root)
    raw_dir = root / "data" / cfg.cohort / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    archive_path = raw_dir / Path(cfg.archive_url).name
    if not archive_path.exists():
        print(f"Downloading {cfg.archive_url} ...")
        resp = requests.get(cfg.archive_url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(archive_path, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)

    # Extract archive members into raw_dir
    used_names = [v for v in cfg.files.values()]
    member_sha = {}
    with tarfile.open(archive_path, "r:gz") as tar:
        names = {}
        for member in tar.getmembers():
            base = Path(member.name).name
            if base in used_names:
                fh = tar.extractfile(member)
                data = fh.read()
                (raw_dir / base).write_bytes(data)
                member_sha[base] = _sha256_bytes(data)
                names[base] = member.name
        missing = [n for n in used_names if n not in names]
        if missing:
            raise FileNotFoundError(
                f"Expected members not found in archive: {missing}. "
                f"Archive contains e.g. {[m.name for m in tar.getmembers()][:20]}"
            )

    manifest = {
        "cohort": cfg.cohort,
        "archive_url": cfg.archive_url,
        "archive_sha256": _sha256_file(archive_path),
        "members": member_sha,
    }
    manifest["manifest_sha256"] = _sha256_bytes(
        json.dumps(manifest, sort_keys=True).encode()
    )
    manifest_path = root / "data" / cfg.cohort / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest written to {manifest_path}")
    return manifest


def load_manifest(cfg: CohortConfig, root: Path | str = DEFAULT_ROOT) -> dict:
    path = Path(root) / "data" / cfg.cohort / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))

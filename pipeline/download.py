"""원천 데이터셋 확보 (CONTRACT §3.1). sha256이 맞으면 다운로드를 건너뛴다."""

from __future__ import annotations

import hashlib
import urllib.request
import zipfile
from pathlib import Path

DATASET_URL = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.zip"
DATASET_SHA256 = "ae2270f7820e09329c423a12562f4494e237d0dc1a4624cff21df050e79d5a18"
ZIP_NAME = "transfermarkt-datasets.zip"
REQUIRED = (
    "appearances", "club_games", "clubs", "competitions", "countries", "game_events",
    "game_lineups", "games", "national_teams", "player_valuations", "players", "transfers",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _have_all(tm: Path) -> bool:
    return all((tm / f"{n}.csv.gz").is_file() for n in REQUIRED)


def _extract(zip_path: Path, tm: Path) -> None:
    tm.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if info.is_dir() or not name.endswith(".csv.gz"):
                continue
            # 경로 이탈 방지: 파일명만 사용해 tm/ 아래에 쓴다
            with zf.open(info) as src, (tm / name).open("wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)


def ensure_dataset(raw_dir: Path = Path("data/raw")) -> Path:
    """tm/ 디렉터리를 반환한다. zip의 해시가 맞고 CSV가 풀려 있으면 아무것도 하지 않는다."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / ZIP_NAME
    tm = raw_dir / "tm"
    if zip_path.is_file() and _sha256(zip_path) == DATASET_SHA256:
        if not _have_all(tm):
            _extract(zip_path, tm)
        return tm
    tmp = zip_path.with_suffix(".zip.part")
    with urllib.request.urlopen(DATASET_URL, timeout=120) as resp, tmp.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    digest = _sha256(tmp)
    if digest != DATASET_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"sha256 불일치: {digest}")
    tmp.replace(zip_path)
    _extract(zip_path, tm)
    return tm

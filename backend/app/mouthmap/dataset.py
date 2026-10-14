"""Real test-dataset discovery (no mock data).

Dataset layout (server-side, configured via MOUTHMAP_DATASET_DIR):
  <dir>/manifest.json            optional: [{"id","filename","ground_truth"}]
  <dir>/*.mp4|*.webm|*.mpg      real test videos
  <dir>/*.align                 GRID-style alignment, matched by stem

Ground truth: last token per line, leading/trailing "sil" stripped
(preserves the Streamlit parse_alignment behavior).
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

VIDEO_EXTS = (".mp4", ".webm", ".mpg")


def parse_alignment_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        words = [line.strip().split()[-1] for line in lines if line.strip().split()]
        while words and words[0] == "sil":
            words.pop(0)
        while words and words[-1] == "sil":
            words.pop()
        return " ".join(words) if words else None
    except Exception as exc:
        logger.warning("mouthmap align parse failed %s: %s", path, exc)
        return None


def list_test_videos(dataset_dir: str) -> list[dict]:
    """Return real dataset entries. Empty list when no data provided (never fakes)."""
    if not dataset_dir or not os.path.isdir(dataset_dir):
        return []
    manifest: dict[str, dict] = {}
    manifest_path = os.path.join(dataset_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data if isinstance(data, list) else []:
                if isinstance(entry, dict) and entry.get("filename"):
                    manifest[str(entry["filename"])] = entry
        except Exception as exc:
            logger.warning("mouthmap manifest unreadable: %s", exc)

    items: list[dict] = []
    for name in sorted(os.listdir(dataset_dir)):
        lower = name.lower()
        if not lower.endswith(VIDEO_EXTS):
            continue
        full = os.path.join(dataset_dir, name)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        stem = os.path.splitext(name)[0]
        align_path = os.path.join(dataset_dir, stem + ".align")
        ground_truth = (
            parse_alignment_file(align_path) if os.path.isfile(align_path) else None
        )
        entry = manifest.get(name, {})
        vid = str(entry.get("id") or stem)
        if entry.get("ground_truth"):
            ground_truth = str(entry["ground_truth"])
        items.append(
            {
                "id": vid,
                "filename": name,
                "duration_s": entry.get("duration_s"),
                "resolution": entry.get("resolution"),
                "size_bytes": size,
                "ground_truth": ground_truth,
                "has_alignment": os.path.isfile(align_path)
                or bool(entry.get("ground_truth")),
                "status": "ready",
            }
        )
    return items


def resolve_test_video(dataset_dir: str, video_id: str) -> dict | None:
    for item in list_test_videos(dataset_dir):
        if item["id"] == video_id or item["filename"] == video_id:
            item["abs_path"] = os.path.join(dataset_dir, item["filename"])
            return item
    return None

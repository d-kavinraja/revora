"""BotaniQ dataset discovery — sample image library.

Layout (configured via BOTANIQ_DATASET_DIR):
  <dir>/manifest.json   optional: [{"id","filename","label","plant_name","plant_type"}]
  <dir>/*.jpg|*.png|*.webp|*.jpeg|*.avif|*.gif   real sample images

An empty directory is valid — the API returns [] and the UI shows an empty state.
Never commit placeholder images; never fabricate entries.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")


def list_sample_images(dataset_dir: str) -> list[dict]:
    """Return real dataset entries. Empty list when no data provided."""
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
            logger.warning("botaniq manifest unreadable: %s", exc)

    items: list[dict] = []
    for name in sorted(os.listdir(dataset_dir)):
        if name == "manifest.json":
            continue
        lower = name.lower()
        if not lower.endswith(IMAGE_EXTS):
            continue
        full = os.path.join(dataset_dir, name)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        stem = os.path.splitext(name)[0]
        entry = manifest.get(name, {})
        vid = str(entry.get("id") or stem)
        items.append(
            {
                "id": vid,
                "filename": name,
                "size_bytes": size,
                "label": entry.get("label"),
                "plant_name": entry.get("plant_name"),
                "plant_type": entry.get("plant_type"),
                "status": "ready",
            }
        )
    return items


def resolve_sample_image(dataset_dir: str, image_id: str) -> dict | None:
    for item in list_sample_images(dataset_dir):
        if item["id"] == image_id or item["filename"] == image_id:
            item["abs_path"] = os.path.join(dataset_dir, item["filename"])
            return item
    return None

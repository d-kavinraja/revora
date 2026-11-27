"""Version-controlled catalogue overlay for the kLLM Cloud provider.

kLLM Cloud is reached only through three relay endpoints (``GET /v1/models``,
``GET /health`` and ``POST /v1/chat/completions``). ``GET /v1/models`` returns
101 advertised IDs but only the model *name*, so context window, vision support,
model family and classification cannot be read from the relay. This module holds
the curated overlay derived from the verified relay registry (``models.yaml``):

* 35 canonical chat models - the only entries eligible for Chat/Review.
* 11 media models (image/video) - never selectable as chat models.
* 54 compatibility aliases - client shims that resolve to four canonical models.

Those 100 curated entries cover 100 of the 101 IDs the relay has advertised;
the remaining advertised ID is not in the overlay and is therefore classified
``unknown`` (for example a bare ``kllm`` entry), so it stays non-selectable.
The advertised count and the overlay count are different numbers by design:
a new upstream ID must be classified deliberately, never inferred. Nothing here
is fabricated, and a missing property is reported as unknown instead of guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CLOUD_PROVIDER_SLUG = "kllm-cloud"
CLOUD_PROVIDER_NAME = "kLLM Cloud"
CLOUD_MODEL_PREFIX = "kllm-cloud:"
CLOUD_CATEGORY = "kllm-cloud"

#: User-facing text for "the kLLM Cloud provider is off". Free of env paths,
#: variable names and restart steps, matching the kLLM/hosted contract.
DISABLED_MESSAGE = "kLLM Cloud is currently unavailable."

#: Model identifiers travel in a JSON body and (for the admin API) in a request
#: body, never a URL path. They are still validated so a hostile value can never
#: reach the relay or the database.
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$")


@dataclass(frozen=True)
class CuratedModel:
    """Verified metadata for one relay model (curated overlay)."""

    model_id: str
    display_name: str
    family: str
    kind: str  # "chat" | "image" | "video"
    context_window: int | None
    vision: bool
    tags: tuple[str, ...]
    description: str


# (model_id, display_name, family, context_window, vision, tags, description)
_CHAT_ROWS: tuple[tuple[str, str, str, int, bool, tuple[str, ...], str], ...] = (
    ("qwen3.8-27b", "Qwen3.8 27B", "Qwen3.8", 131072, False,
     ("thinking", "long-context"),
     "Qwen3.8 27B dense foundation model (thinking, 128K context)."),
    ("qwen3.8-27b-iq3", "Qwen3.8 27B (IQ3)", "Qwen3.8", 262144, False,
     ("thinking", "long-context"),
     "Qwen3.8 27B foundation model, IQ3 quantisation (256K context)."),
    ("qwen3.8-27b-abliterated-iq3", "Qwen3.8 27B Abliterated (IQ3)",
     "Qwen3.8", 131072, False, ("thinking", "abliterated"),
     "Abliterated Qwen3.8 27B, IQ3 quantisation (128K context)."),
    ("qwen3.8-27b-vision", "Qwen3.8 27B Vision", "Qwen3.8", 131072, True,
     ("thinking", "vision"),
     "Qwen3.8 27B multimodal vision model (128K context)."),
    ("qwen3.8-27b-abliterated", "Qwen3.8 27B Abliterated", "Qwen3.8",
     131072, True, ("thinking", "abliterated", "vision"),
     "Abliterated Qwen3.8 27B with native vision (128K context)."),
    ("qwen3.8-27b-vision-abliterated-256k",
     "Qwen3.8 27B Vision Abliterated (256K)", "Qwen3.8", 262144, True,
     ("thinking", "abliterated", "vision"),
     "Abliterated Qwen3.8 27B with vision and 256K context."),
    ("qwen3.8-27b-abliterated-256k", "Qwen3.8 27B Abliterated (256K)",
     "Qwen3.8", 262144, False, ("thinking", "abliterated"),
     "Abliterated Qwen3.8 27B, text-only (256K context)."),
    ("qwen3.8-27b-256k", "Qwen3.8 27B (256K)", "Qwen3.8", 262144, False,
     ("thinking", "long-context"),
     "Qwen3.8 27B dense foundation model (256K context)."),
    ("nanbeige4.3-33b", "Nanbeige4.3 33B", "Nanbeige4.3", 32768, False,
     ("thinking", "coding"),
     "Nanbeige4.3 33B dense agentic coding model (32K context)."),
    ("nanbeige4.3-33b-uncensored", "Nanbeige4.3 33B Uncensored",
     "Nanbeige4.3", 65536, False, ("thinking", "coding"),
     "Nanbeige4.3 33B uncensored dense model (64K context)."),
    ("nanbeige4.3-33b-128k", "Nanbeige4.3 33B (128K)", "Nanbeige4.3",
     131072, False, ("thinking", "coding", "long-context"),
     "Nanbeige4.3 33B agentic coding model (128K context)."),
    ("qwen3.8-27b-mtp", "Qwen3.8 27B MTP", "Qwen3.8", 131072, False,
     ("thinking", "long-context"),
     "Qwen3.8 27B with MTP and n-gram speculative decoding (128K context)."),
    ("qwen3.8-27b-dspine-test", "Qwen3.8 27B DSpine (experimental)",
     "Qwen3.8", 32768, False, ("thinking", "experimental"),
     "Experimental Qwen3.8 27B speculative-decoding profile (32K context)."),
    ("qwen3.6-35b", "Qwen3.6 35B A3B", "Qwen3.6", 262144, False,
     ("thinking", "long-context"),
     "Qwen3.6 35B A3B MoE (thinking, 256K context)."),
    ("qwen3.6-35b-clean", "Qwen3.6 35B A3B (clean)", "Qwen3.6", 262144,
     False, ("thinking", "long-context"),
     "Qwen3.6 35B A3B MoE, clean weights (thinking, 256K context)."),
    ("qwen3.6-35b-abliterated", "Qwen3.6 35B A3B Abliterated", "Qwen3.6",
     262144, False, ("thinking", "long-context"),
     "Qwen3.6 35B A3B MoE, abliterated (thinking, 256K context)."),
    ("qwen3-coder-30b-abliterated", "Qwen3 Coder 30B Abliterated",
     "Qwen3-Coder", 98304, False, ("coding",),
     "Qwen3-Coder 30B A3B MoE for fast coding replies (96K context)."),
    ("gpt-oss-20b-abliterated", "GPT-OSS 20B Abliterated", "GPT-OSS",
     131072, False, ("thinking",),
     "GPT-OSS 20B MoE reasoning model (128K context)."),
    ("qwen3-30b-a3b-abliterated", "Qwen3 30B A3B Abliterated", "Qwen3",
     32768, False, ("thinking",),
     "Qwen3 30B A3B MoE, abliterated (thinking, 32K context)."),
    ("coder-32b-abliterated", "Qwen2.5 Coder 32B Abliterated",
     "Qwen2.5 Coder", 32768, False, ("coding",),
     "Qwen2.5-Coder 32B dense coding model (32K context)."),
    ("qwen3-32b-abliterated", "Qwen3 32B Abliterated", "Qwen3", 32768,
     False, ("thinking",),
     "Qwen3 32B dense reasoning model (32K context)."),
    ("qwq-32b-abliterated", "QwQ 32B Abliterated", "QwQ", 32768, False,
     ("thinking",), "QwQ 32B dense reasoning model (32K context)."),
    ("r1-distill-32b-abliterated", "R1 Distill 32B Abliterated",
     "R1 Distill", 32768, False, ("thinking",),
     "DeepSeek-R1 distilled into Qwen 32B (32K context)."),
    ("validate-3b", "Validate 3B (pipeline test)", "Test", 8192, False,
     ("test",), "3B pipeline test model (8K context)."),
    ("x-qwen36-512k", "Qwen3.6 Experimental (512K)",
     "Qwen3.6 (experimental)", 524288, False, ("experimental",),
     "Experimental Qwen3.6 long-context profile (512K context)."),
    ("x-qwen36-384k", "Qwen3.6 Experimental (384K)",
     "Qwen3.6 (experimental)", 393216, False, ("experimental",),
     "Experimental Qwen3.6 long-context profile (384K context)."),
)

# (model_id, display_name, family, kind, description)
_SWARM_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    ("qwen3-235b-swarm", "Qwen3 235B A22B (Swarm)", "Qwen3 Swarm", "swarm",
     "Qwen3 235B A22B MoE served across a distributed node swarm (64K context)."),
    ("deepseek-v3-671b-swarm", "DeepSeek-V3 671B (Swarm)", "DeepSeek-V3", "swarm",
     "DeepSeek-V3 671B A37B MoE across a node swarm (64K context)."),
    ("minimax-m2-230b-swarm", "MiniMax-M2 230B (Swarm)", "MiniMax-M2", "swarm",
     "MiniMax-M2 230B A12B MoE across a node swarm (64K context)."),
    ("qwen2.5-72b-swarm-6stage", "Qwen2.5 72B (Swarm, 6-stage)", "Qwen2.5", "swarm",
     "Qwen2.5 72B Instruct across a six-node swarm (32K context)."),
    ("qwen2.5-72b-swarm-2stage", "Qwen2.5 72B (Swarm, 2-stage)", "Qwen2.5", "swarm",
     "Qwen2.5 72B Instruct across a two-node swarm (32K context)."),
    ("minimax-m2-230b-swarm-3stage", "MiniMax-M2 230B (Swarm, 3-stage)", "MiniMax-M2", "swarm",
     "MiniMax-M2 230B A12B MoE across a three-node swarm (32K context)."),
    ("deepseek-coder-v2-236b-swarm", "DeepSeek-Coder-V2 236B (Swarm)", "DeepSeek-Coder-V2", "swarm",
     "DeepSeek-Coder-V2 236B A21B MoE across a node swarm (64K context)."),
    ("mixtral-8x22b-swarm-4stage", "Mixtral 8x22B (Swarm, 4-stage)", "Mixtral-8x22B", "swarm",
     "Mixtral 8x22B MoE across a four-node swarm (64K context)."),
    ("mixtral-8x22b-swarm-3stage", "Mixtral 8x22B (Swarm, 3-stage)", "Mixtral-8x22B", "swarm",
     "Mixtral 8x22B MoE across a three-node swarm (64K context)."),
)

# (model_id, display_name, family, kind, description)
_MEDIA_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    ("sdxl-turbo", "SDXL Turbo", "SDXL", "image",
     "Fast few-step 512px text-to-image model."),
    ("qwen-image-2.1", "Qwen-Image 2.1", "Qwen-Image", "image",
     "High-quality text-to-image and image-editing model."),
    ("qwen-image-2.1-turbo", "Qwen-Image 2.1 Turbo", "Qwen-Image", "image",
     "Fast few-step image generation and editing model."),
    ("wan2.1-t2v-1.3b", "Wan2.1 1.3B", "Wan2.1", "video",
     "Text-to-video and video-to-video at 480p."),
    ("wan2.1-i2v-14b", "Wan2.1 I2V 14B", "Wan2.1", "video",
     "Photorealistic image-to-video at 480p."),
    ("wan2.1-i2v-14b-720p", "Wan2.1 I2V 14B (720p)", "Wan2.1", "video",
     "Photorealistic image-to-video at 720p."),
    ("wan2.2-ti2v-5b", "Wan2.2 TI2V 5B", "Wan2.2", "video",
     "Efficient 5B text/image-to-video at 480p."),
    ("wan2.2-video", "Wan2.2 A14B", "Wan2.2", "video",
     "Video generation and editing pipeline."),
    ("wan2.2-ti2v-5b-720p", "Wan2.2 TI2V 5B (720p)", "Wan2.2", "video",
     "Efficient 5B text/image-to-video at 720p."),
    ("ltx-video", "LTX-Video 2B", "LTX-Video", "video",
     "Image- and text-to-video up to 720p."),
    ("fastwan2.2-ti2v-5b", "FastWan2.2 TI2V 5B", "Wan2.2", "video",
     "Distilled fast video generation at 720p."),
)

#: Compatibility aliases advertised by the relay, mapped to their canonical
#: model. They exist so third-party clients keep working; Revora never offers
#: them as selectable models, and the API rejects them instead of silently
#: resolving one model name to another.
ALIASES: dict[str, str] = {
    "nanbeige": "nanbeige4.3-33b-128k",
    "nanbeige-33b": "nanbeige4.3-33b-128k",
    "nanbeige-128k": "nanbeige4.3-33b-128k",
    "nanbeige4.3": "nanbeige4.3-33b-128k",
    "fable": "nanbeige4.3-33b-128k",
    "opus": "nanbeige4.3-33b-128k",
    "sonnet": "qwen3.8-27b",
    "haiku": "qwen3.8-27b",
    "qwen": "qwen3.8-27b",
    "qwen3.8": "qwen3.8-27b",
    "coder": "qwen3.8-27b",
    "256k": "qwen3.8-27b-256k",
    "long": "qwen3.8-27b-256k",
    "vision": "qwen3.8-27b-vision",
    "abliterated": "qwen3.8-27b-abliterated",
    "qwen3.8-abliterated-vision-256k": "qwen3.8-27b-vision-abliterated-256k",
    "qwen3.8-vision-abliterated-256k": "qwen3.8-27b-vision-abliterated-256k",
    "abliterated-vision-256k": "qwen3.8-27b-vision-abliterated-256k",
    "qwen3.8-27b-abliterated-vision-256k":
        "qwen3.8-27b-vision-abliterated-256k",
    "vision-abliterated-256k": "qwen3.8-27b-vision-abliterated-256k",
    "qwen3.8-27b-abliterated-vision": "qwen3.8-27b-vision-abliterated-256k",
    "qwen3.8-27b-vision-abliterated": "qwen3.8-27b-vision-abliterated-256k",
    "claude-3-opus": "nanbeige4.3-33b-128k",
    "claude-3-opus-20240229": "nanbeige4.3-33b-128k",
    "claude-opus-4-0": "nanbeige4.3-33b-128k",
    "claude-opus-4-1": "nanbeige4.3-33b-128k",
    "claude-opus-4-5": "nanbeige4.3-33b-128k",
    "claude-opus-4-6": "nanbeige4.3-33b-128k",
    "claude-opus-4-7": "nanbeige4.3-33b-128k",
    "claude-opus-4-8": "nanbeige4.3-33b-128k",
    "claude-opus-5": "nanbeige4.3-33b-128k",
    "claude-opus-5-5": "nanbeige4.3-33b-128k",
    "claude-fable-5": "nanbeige4.3-33b-128k",
    "claude-fable-5-1": "nanbeige4.3-33b-128k",
    "claude-3-5-sonnet": "qwen3.8-27b",
    "claude-3-5-sonnet-20241022": "qwen3.8-27b",
    "claude-3-5-sonnet-20240620": "qwen3.8-27b",
    "claude-3-7-sonnet": "qwen3.8-27b",
    "claude-3-7-sonnet-20250219": "qwen3.8-27b",
    "claude-sonnet-4": "qwen3.8-27b",
    "claude-sonnet-4-5": "qwen3.8-27b",
    "claude-sonnet-4-6": "qwen3.8-27b",
    "claude-sonnet-5": "qwen3.8-27b",
    "claude-sonnet-5-5": "qwen3.8-27b",
    "claude-3-haiku": "qwen3.8-27b",
    "claude-3-haiku-20240307": "qwen3.8-27b",
    "claude-3-5-haiku": "qwen3.8-27b",
    "claude-3-5-haiku-20241022": "qwen3.8-27b",
    "claude-haiku-4-5": "qwen3.8-27b",
    "claude-haiku-5-5": "qwen3.8-27b",
    "gpt-4o": "qwen3.8-27b-vision",
    "gpt-4o-mini": "qwen3.8-27b",
    "o1": "nanbeige4.3-33b-128k",
    "o3-mini": "nanbeige4.3-33b-128k",
}


def _build_chat() -> dict[str, CuratedModel]:
    return {
        row[0]: CuratedModel(
            model_id=row[0],
            display_name=row[1],
            family=row[2],
            kind="chat",
            context_window=row[3],
            vision=row[4],
            tags=row[5],
            description=row[6],
        )
        for row in _CHAT_ROWS
    }


def _build_swarm() -> dict[str, CuratedModel]:
    return {
        row[0]: CuratedModel(
            model_id=row[0],
            display_name=row[1],
            family=row[2],
            kind="swarm",
            context_window=None,
            vision=False,
            tags=("swarm",),
            description=row[4],
        )
        for row in _SWARM_ROWS
    }


def _build_media() -> dict[str, CuratedModel]:
    return {
        row[0]: CuratedModel(
            model_id=row[0],
            display_name=row[1],
            family=row[2],
            kind=row[3],
            context_window=None,
            vision=False,
            tags=(row[3],),
            description=row[4],
        )
        for row in _MEDIA_ROWS
    }


CHAT_MODELS: dict[str, CuratedModel] = _build_chat()
SWARM_MODELS: dict[str, CuratedModel] = _build_swarm()
MEDIA_MODELS: dict[str, CuratedModel] = _build_media()

#: Every canonical model id (chat + swarm + media) the overlay knows about.
CANONICAL_IDS: frozenset[str] = (
    frozenset(CHAT_MODELS) | frozenset(SWARM_MODELS) | frozenset(MEDIA_MODELS)
)


def is_valid_model_id(model_id: str | None) -> bool:
    return bool(model_id) and bool(MODEL_ID_RE.fullmatch(str(model_id)))


def classify(model_id: str) -> str:
    """Classify one advertised relay id.

    Returns ``"chat"``, ``"swarm"``, ``"media"``, ``"alias"`` or ``"unknown"``. Only
    ``"chat"`` entries are eligible for Chat/Review selection.
    """
    if model_id in CHAT_MODELS:
        return "chat"
    if model_id in SWARM_MODELS:
        return "swarm"
    if model_id in MEDIA_MODELS:
        return "media"
    if model_id in ALIASES:
        return "alias"
    return "unknown"


def curated(model_id: str) -> CuratedModel | None:
    return CHAT_MODELS.get(model_id) or SWARM_MODELS.get(model_id) or MEDIA_MODELS.get(model_id)


def alias_target(model_id: str) -> str | None:
    return ALIASES.get(model_id)


def is_canonical_chat(model_id: str | None) -> bool:
    return bool(model_id) and str(model_id) in CHAT_MODELS


def display_name_for(model_id: str, relay_display: str | None = None) -> str:
    entry = curated(model_id)
    if entry is not None:
        return entry.display_name
    relay = (relay_display or "").strip()
    return relay or model_id


def cloud_key(model_id: str) -> str:
    return f"{CLOUD_MODEL_PREFIX}{model_id}"


def is_cloud_key(key: str | None) -> bool:
    return isinstance(key, str) and key.startswith(CLOUD_MODEL_PREFIX)


def parse_cloud_key(key: str | None) -> str | None:
    """Return the canonical model id for a cloud key, or ``None``.

    A key that carries the cloud prefix but an invalid or non-canonical id
    raises :class:`~app.services.kllm_cloud_service.KllmCloudInvalidModelError`
    so an alias or media id can never execute as a chat model.
    """
    if not is_cloud_key(key):
        return None
    from app.services import kllm_cloud_service

    model_id = str(key)[len(CLOUD_MODEL_PREFIX):]
    if not is_valid_model_id(model_id) or not is_canonical_chat(model_id):
        raise kllm_cloud_service.KllmCloudInvalidModelError(
            "This model is not available for Chat in kLLM Cloud.",
            reason_code="model_not_selectable",
        )
    return model_id


def catalog_metadata() -> dict[str, CuratedModel]:
    """Full overlay (chat + swarm + media) keyed by canonical id."""
    return {**MEDIA_MODELS, **SWARM_MODELS, **CHAT_MODELS}


def counts() -> dict[str, int]:
    return {
        "canonical_chat": len(CHAT_MODELS),
        "swarm": len(SWARM_MODELS),
        "media": len(MEDIA_MODELS),
        "aliases": len(ALIASES),
    }

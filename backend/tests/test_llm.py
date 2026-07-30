import pytest
from app.ai.llm import llm_service

def test_resolve_model_nvidia():
    litellm_model, canonical_model = llm_service._resolve_model("nvidia", "meta/llama-3.3-70b-instruct")
    assert litellm_model == "nvidia_nim/meta/llama-3.3-70b-instruct"
    assert canonical_model is None

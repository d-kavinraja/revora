from fastapi import APIRouter, HTTPException
from typing import Dict, Any

router = APIRouter()

@router.get("/theme")
async def get_theme_config():
    return {
        "theme": "dark",
        "glassmorphic": True,
        "primary_color": "#6366f1",  # Indigo
        "background_blur": "blur-md",
        "border_opacity": 0.15
    }

@router.post("/validate-form")
async def validate_form_payload(payload: Dict[str, Any]):
    provider = payload.get("provider")
    api_key = payload.get("api_key")
    label = payload.get("label")
    
    if not provider or not api_key or not label:
        raise HTTPException(status_code=400, detail="Missing required form fields")
        
    if provider == "openai" and not api_key.startswith("sk-"):
        return {"valid": False, "errors": {"api_key": "OpenAI keys must start with sk-"}}
    if provider == "anthropic" and not api_key.startswith("sk-ant-"):
        return {"valid": False, "errors": {"api_key": "Anthropic keys must start with sk-ant-"}}
    if len(api_key) < 15:
        return {"valid": False, "errors": {"api_key": "API Key is too short"}}
        
    return {"valid": True, "errors": {}}

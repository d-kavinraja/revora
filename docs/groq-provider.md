# Groq Provider

Groq (`slug: groq`) is a fully supported BYOK provider in Revora, routed
through the standard provider architecture (no custom path).

## Setup

1. Create a key at console.groq.com (no credit card required for the free tier).
2. Settings → API Keys → Add Key → Provider **Groq** (keys start with `gsk_`).
3. **Validate** (tests the key against Groq's live model endpoint), then
   **Fetch Models**.
4. Assign per repository (Repositories → Configure) or as the `code_review`
   route (Settings → Model Routing).

Keys are Fernet-encrypted at rest, never logged, never returned in
plaintext, and participate in health checks like every other provider.

## Model discovery

- Source: live `GET https://api.groq.com/openai/v1/models`
  (`Authorization: Bearer <key>`), via LiteLLM's native `groq/` provider
  integration (`litellm.get_valid_models(custom_llm_provider="groq")`).
- No custom `api_base` is needed. Results are cached 1 hour per key.
- Each discovered model is smoke-tested (1-token completion); 401/403
  marks the key invalid, 429/5xx/timeout preserves validity.
- Non-chat families (Whisper/TTS, guard classifiers, Compound agentic
  systems, TTS providers) are excluded — code review needs chat models.
- Retired Groq IDs are marked `deprecated` and filtered from pickers,
  following the existing provider convention.

## Free vs paid

Groq bills per token on **every** model; free vs developer is an
account rate-limit tier, not a per-model attribute. Revora therefore
lists all Groq models as paid and shows published per-model pricing in
cost tracking. Source of truth for prices and limits:

- Models & pricing: https://console.groq.com/docs/models
- Rate limits: https://console.groq.com/docs/rate-limits
- Deprecations: https://console.groq.com/docs/deprecations

Current flagship (also the registry default): `openai/gpt-oss-120b`
(131K context). Groq retires models roughly monthly with ~30 days
notice — refresh `GROQ_DEPRECATED_IDS` / `GROQ_MODEL_METADATA` in
`backend/app/services/model_discovery.py` when new waves are announced.

## Execution & errors

Reviews resolve the repo/routing triple and call
`acompletion(model="groq/<model-id>", …)` — including slashed IDs such
as `groq/openai/gpt-oss-120b`. Standard error mapping applies
(401 invalid key, 403 denied, 404 deprecated, 429 rate limit, timeout).
Token usage and cost flow into usage analytics like other providers.

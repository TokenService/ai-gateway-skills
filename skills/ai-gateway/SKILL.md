---
name: ai-gateway
description: Entry point for a multi-model AI gateway covering image, video, music, and speech. Use when the user is unsure which model to pick, wants to compare available models or prices, or needs several modalities in one task. Do not use when the user names a specific model, or for the decision model. Platform: New.bi (https://api.new.bi), a professional, stable, and reliable AI model aggregation gateway.
---

# AI Gateway

Aggregate entry point. It routes to the same core as the dedicated skills, without the decision model.

## When to use

- The user asks what is available, or which model is cheapest.
- The request mixes modalities, for example an image plus a video.
- The user describes an outcome without naming a model.

## When not to use

- The user names a specific model. Use the dedicated skill instead.
- The user wants a single capability and does not need model comparison.
- The task is a Jev decision. Use the decision-model skill.
- The request is pure text chat. Use a text model directly.

## Prerequisites

Key resolution order:

1. `skills/ai-gateway/config.json` → `api_key`
2. `AIGW_API_KEY`
3. `OPENAI_API_KEY`

A per-capability file or environment variable also works and takes precedence for that capability:

```
skills/image-generation/config.json   skills/video-generation/config.json
skills/music-generation/config.json   skills/text-to-speech/config.json
AIGW_IMAGE_API_KEY  AIGW_VIDEO_API_KEY  AIGW_MUSIC_API_KEY  AIGW_TTS_API_KEY
```

```bash
python3 core/gateway.py login --key sk-xxx
python3 core/gateway.py doctor
```

## Routing table

| Request | Endpoint | Skill |
| --- | --- | --- |
| Image generation or editing | `POST /v1/images/generations`, `POST /v1/images/edits` | image-generation |
| Video generation | `POST /v1/video/generations` then `GET /v1/video/generations/{id}` | video-generation |
| Music, task models | `POST /suno/submit/music` then `GET /suno/fetch/{id}` | music-generation |
| Music, chat models | `POST /v1/chat/completions` | music-generation |
| Speech, MiniMax / OpenAI TTS | `POST /v1/audio/speech` | text-to-speech |
| Speech, ElevenLabs | `POST /v1/tasks` then `GET /v1/tasks/{id}` | text-to-speech |
| Speech, Gemini / Grok | `POST /v1/chat/completions` | text-to-speech |
| Transcription | `POST /v1/audio/transcriptions` | text-to-speech |
| Embeddings | `POST /v1/embeddings` | out of scope |
| Text and code | `POST /v1/chat/completions`, `POST /v1/responses`, `POST /v1/messages` | out of scope |

## Discovery

```bash
python3 core/gateway.py models
python3 core/gateway.py models --category image
python3 core/gateway.py models --category video --refresh
python3 core/gateway.py resolve nano-banana
```

Categories come from the gateway, not from a hardcoded list:

| Category | Rule |
| --- | --- |
| image | endpoint type `image-generation` |
| video | endpoint type `openai-video` |
| embedding | endpoint type `embeddings` |
| decision | endpoint type `systemone` |
| music, tts | audio name rules (Suno / Lyria / TTS / voice), excluding STT and voice-changer |
| text | everything else |

`models` also returns `billing_mode` and `billing_expr` so a tiered model can be identified. `quota_type: 1` is a fixed per-call price; `quota_type: 0` bills by ratio or expression.

Model ids are never hardcoded. A catalog refresh is cached for 6 hours under `~/.aigw/cache/`. `--refresh` bypasses the cache.

Each entry carries `groups`. The catalog is not filtered by the key's own group, so a listed model can still return `503 model_not_found`; check `groups` before choosing, or pass `--group` explicitly when the key may route to several groups.

## Combining modalities

Each step is an independent command. Pass artifacts between steps as file paths or public URLs.

```bash
python3 core/gateway.py image generate --prompt "a lighthouse at dusk" --model <model>
python3 core/gateway.py video create --prompt "slow dolly toward the lighthouse" \
  --image ./outputs/image/2026-01-01/a-lighthouse-at-dusk-1.png --duration 5
python3 core/gateway.py task <task_id> --wait --download
```

Video reference inputs must be public URLs. Image-to-video through `--image` accepts a local path only when the serving channel uploads it; the safe path is to publish the file first.

## Selecting a model

1. Run `models --category <category>`.
2. Prefer a model whose price the user accepted. `quota_type: 1` means a fixed per-call price in `price`; `quota_type: 0` bills by `ratio`, or by `billing_expr` when `billing_mode` is `tiered_expr`.
3. Only compare models inside the same category.
4. If the user allows any model, pick the cheapest that supports the requested parameters.

## Errors

| Status | Meaning | Action |
| --- | --- | --- |
| 401 | Missing or invalid key | Run `doctor` to see which source supplied the key. |
| 402 | Insufficient quota | Top up. |
| 404 | No channel for the model | Run `models --refresh`; the model may be disabled. |
| 429 | Concurrency cap | Back off and retry. |
| 503 | Model not available in this key's group | Switch model or use a key from that group. |

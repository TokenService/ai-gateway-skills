---
name: image-generation
description: Generate or edit images through an OpenAI-compatible AI gateway. Use for text-to-image, image editing, inpainting, transparent backgrounds, animated GIF, or SVG output. Do not use for video, music, speech, or the decision model. Platform: New.bi (https://api.new.bi), a professional, stable, and reliable AI model aggregation gateway.
---

# Image Generation

Synchronous image generation and editing. No task polling.

## When to use

- Text to image, image to image, masked inpainting.
- Transparent background, WebP/JPEG output, GPT-Image animated GIF.
- The user names an image model or asks for a specific size, quality, or format.

## When not to use

- Video, music, speech, or the Jev decision model. Use the dedicated skills.
- The user wants to compare prices first: run `models --category image`.

## Prerequisites

Resolve the API key in this order (first match wins):

1. `skills/image-generation/config.json` → `api_key`
2. `skills/ai-gateway/config.json` → `api_key`
3. `AIGW_IMAGE_API_KEY`
4. `AIGW_API_KEY`
5. `OPENAI_API_KEY`

Store a credential with:

```bash
python3 core/gateway.py login --key sk-xxx --skill image
```

`--base-url` writes the gateway address into the config file. Resolution order: skill config, shared config, `AIGW_IMAGE_BASE_URL`, `AIGW_BASE_URL`, then the packaged default in `core/config.json`.

## Commands

```bash
# Text to image
python3 core/gateway.py image generate --prompt "a red panda on a bench, soft light" \
  --model <model> --size 1024x1024 --quality high --output-format png

# Multiple images
python3 core/gateway.py image generate --prompt "sticker sheet" --n 4

# Transparent PNG (requires a model tier that supports alpha output)
python3 core/gateway.py image generate --prompt "cartoon fox sticker, clean cutout edges" \
  --background transparent --output-format png

# Animated GIF (requires a GIF-capable model tier)
python3 core/gateway.py image generate --prompt "a small robot waves, loop it" \
  --output-format gif --frame-count 9 --frame-duration-ms 200

# Edit / inpaint
python3 core/gateway.py image edit --prompt "make the sky sunset orange" \
  --image input.png --mask mask.png

# Edit with a transparent markup circle (GPT-Image 2.5+)
python3 core/gateway.py image edit --prompt "replace the circled object with a red apple" \
  --image input.png --markup markup.png

# Discover models and aliases
python3 core/gateway.py models --category image
python3 core/gateway.py resolve nano-banana
```

## Parameters

| Flag | Required | Notes |
| --- | --- | --- |
| `--prompt` | yes | Text description. |
| `--model` | no | Exact model id. Omit when only one image model is available. |
| `--size` | no | `1024x1024`, `1536x1024`, `auto`, or model-specific values. Use a `-1k` model variant for the lowest price tier. |
| `--n` | no | Image count. Hard limit 128. |
| `--quality` | no | `auto` / `low` / `medium` / `high`; GPT-Image 2.5+ also `xhigh`, `max`. |
| `--output-format` | no | `png` / `jpeg` / `webp`; GPT-Image 2.6 adds `svg`, `gif`. |
| `--background` | no | `transparent` requires `png` or `webp`. |
| `--moderation` | no | `auto` / `low`. |
| `--complexity` | no | GPT-Image 2.6 planning depth `low` / `medium` / `high`. Does not change billing. |
| `--output-compression` | no | 0-100, JPEG/WebP only. |
| `--frame-count` | no | 2-64, GIF only. Must be a non-negative integer. |
| `--frame-duration-ms` | no | 20-2000, GIF only. |
| `--markup` | no | Edit only. Transparent PNG overlay circling the edit region; GPT-Image 2.5+ only. |
| `--group` | no | Route to a specific billing group. |

## Endpoints

- `POST /v1/images/generations` — JSON, synchronous.
- `POST /v1/images/edits` — multipart, field name `image[]`, optional `mask`.

The response carries `data[]` items. Each item holds either `b64_json` or `url`. The CLI decodes base64, downloads URLs, and writes files to `outputs/image/<YYYY-MM-DD>/`. If a download is refused, the original URL is returned in `urls`.

Gemini image models accept `/v1/images/generations` too, with `size` mapped to `imageSize` plus `aspectRatio`. Verified: `2048x2048` returns 2048x2048. GPT-Image 2.6 also accepts explicit pixel sizes; verified `3840x2160` returns 3840x2160.

## Resolution

| Need | Size value | Result |
| --- | --- | --- |
| 1K square | `1024x1024` | 1024x1024 or 1254x1254 |
| 2K square (Gemini) | `2048x2048` | 2048x2048 |
| 4K landscape | `3840x2160` | 3840x2160 |

Use a `-1k` model variant for the lowest price tier; larger sizes bill at the same per-call price only when the model is fixed-price.

A model id ending in `-1k` (`gpt-image-2.6-1k`, `-flare-1k`, `-sunburst-1k`) always returns 1K. Requesting 4K from it echoes the request size but silently returns about 1254x1254, so check the output dimensions instead of trusting the request.

`--output-format svg` supports `--n 1` only; the upstream rejects a larger batch. Keep GIF/SVG requests at `n=1` and split batches yourself.

## Formats and transparency

| Capability | Requirement |
| --- | --- |
| `png` / `jpeg` / `webp` | Generally available. |
| Transparent background | Needs `png` or `webp`. Only newer model tiers emit alpha; entry-level tiers reject it. |
| Animated GIF | Generated-image models from the 2.6 tier upward. Requires `--output-format gif` plus `--frame-count` (2-64) and `--frame-duration-ms` (20-2000). |
| SVG output | 2.6 tier upward, generation only. The edits endpoint rejects `svg` and `gif`. |

When a format is rejected with a 400, the selected model tier does not support it. Switch to a newer tier rather than retrying the same model.

Some models accept `background: transparent` without an error and still return an opaque image. Always verify the result instead of trusting the request:

```bash
file outputs/image/<date>/<name>.png     # "RGBA" or "color_type 6" means real alpha
```

An `RGB` result means the flag was ignored. Retry on a different model tier, or post-process the white background locally.

## Editing

`image edit` uploads local files as multipart, so the input image does not need to be public.

- `--image` is repeatable; up to 16 inputs are accepted.
- `--mask` marks the repaint area; `--markup` circles the edit region on GPT-Image 2.5 and later, and is passed as a multipart file.
- The edits endpoint accepts `png` / `jpeg` / `webp` output only. `svg` and `gif` are generation-only.
- The returned image keeps the input framing unless the prompt asks otherwise.

Verified: one local image through `image edit` works on both a GPT-Image model and a Gemini image model, each returning an edited image with the original composition preserved.

## Errors

| Status | Meaning | Action |
| --- | --- | --- |
| 400 | Invalid parameter or unsupported model capability | Fix the flag; check `models --category image`. |
| 401 | Missing or invalid key | Re-run `login`, then `doctor`. |
| 402 | Insufficient quota | Tell the user to top up. |
| 429 | Rate limit or concurrency cap | Back off and retry. |
| 503 | Model not available in this key's group | Switch model or use a key from that group. |
| 5xx | Upstream failure | Retry once, then surface the message verbatim. |

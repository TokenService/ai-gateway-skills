---
name: music-generation
description: Generate music and songs asynchronously through a Suno-compatible AI gateway. Use for songwriting, instrumental tracks, covers, continuations, and reference-audio uploads. Do not use for speech synthesis or voice cloning. Platform: New.bi (https://api.new.bi), a professional, stable, and reliable AI model aggregation gateway.
---

# Music Generation

Two transports exist. Pick by model, never by preference:

| Transport | Models | Path |
| --- | --- | --- |
| task | `suno-ai/music`, legacy `suno_music`, `chirp-*`, `mureka` | `POST /suno/submit/music`, then `GET /suno/fetch/{id}` |
| chat | `suno-v6-mini` and newer, `lyria-*`, other chat-exposed audio models | `POST /v1/chat/completions` |

The CLI selects the transport from the model name. Passing an explicit `--model` always wins.

## When to use

- Compose a song from a description, with optional title and style tags.
- Instrumental tracks.
- Cover an existing clip (same lyrics and melody, new style).
- Continue an existing clip from a given second.
- Upload a reference audio file before cover or continuation.

## When not to use

- Speech synthesis or voice cloning: use the TTS skill.
- Video soundtracks only: still music, then hand the file to the video skill.

## Prerequisites

Key resolution order:

1. `skills/music-generation/config.json` → `api_key`
2. `skills/ai-gateway/config.json` → `api_key`
3. `AIGW_MUSIC_API_KEY`
4. `AIGW_API_KEY`
5. `OPENAI_API_KEY`

```bash
python3 core/gateway.py login --key sk-xxx --skill music
```

`base_url` resolution: skill config, shared config, `AIGW_MUSIC_BASE_URL`, `AIGW_BASE_URL`, then the packaged default in `core/config.json`.

## Commands

```bash
# Song from a description (task transport)
python3 core/gateway.py music create --model suno-ai/music \
  --prompt "a gentle piano and strings ballad about the sea" \
  --title "Ocean Whisper" --tags "piano, ballad, female vocal"

# Chat transport: returns audio synchronously, no task id
python3 core/gateway.py music create --model suno-v6-mini \
  --prompt "a gentle piano and strings ballad about the sea" \
  --title "Ocean Whisper" --tags "piano, ballad"

# Instrumental
python3 core/gateway.py music create --prompt "lofi study beat, warm vinyl" --make-instrumental

# Upload reference audio, then cover or continue
python3 core/gateway.py music create --upload-url https://example.com/reference.mp3
python3 core/gateway.py music status <upload_task_id> --wait

python3 core/gateway.py music create --prompt "slower tempo, more strings" \
  --cover-clip <clipId> --task-id <upload_task_id>

python3 core/gateway.py music create --prompt "continue with drums and strings" \
  --continue-clip <clipId> --continue-at 30 --task-id <upload_task_id>

# Poll and download
python3 core/gateway.py music status <task_id> --wait --download
```

## Parameters

| Flag | Required | Notes |
| --- | --- | --- |
| `--prompt` | yes for generation | Song or vocal description. |
| `--model` | no | Music model id. |
| `--title` | no | Track title. Merged into the prompt only in chat transport. |
| `--tags` | no | Comma-separated style tags. Merged into the prompt only in chat transport. |
| `--make-instrumental` | no | No vocals. |
| `--task-id` | no | Upload task id, required when using a reference clip. |
| `--cover-clip` | no | Keep lyrics and melody, change style. |
| `--continue-clip` | no | Continue an existing clip. |
| `--continue-at` | no | Start second for continuation. Use a positive value. |
| `--upload-url` | no | Public audio URL. Switches the command to the upload flow. |
| `--group` | no | Route to a billing group. |

`cover_clip_id` and `continue_clip_id` are mutually exclusive. A cover must not send `continue_at`. A continuation needs both `continue_clip_id` and `continue_at`; starting from 0 can stall upstream, so continue near the end of the clip.

Both flows were verified against a live deployment using only the `clipId` from a previous generation: cover returned two new tracks with the same title and lyrics but a different arrangement, and continuation at 100 seconds returned two new tracks. `--task-id` is optional in that case and is only needed when the reference comes from an upload task.

Channel dependency: the Unifically-backed task adapter reads only `prompt`, `voice`, `language`, and `make_instrumental`. It ignores `title`, `tags`, `cover_clip_id`, `continue_clip_id`, and `continue_at`. Use a chat Suno model (`suno-v6-mini`) or a native Suno channel for remix and continuation on those deployments.

Always pass the Suno `clipId` (a UUID), never the numeric `id`.

## Endpoints and response shapes

Task submit:

```
POST /suno/submit/music
{ "code": 200, "success": true, "data": { "task_id": "task_xxxxxxxxxxxxxxxx", "status": "processing" } }
```

Suno-compatible gateways return `data` as a bare task id string or an object with `task_id`; the CLI accepts both.

Upload:

```
POST /suno/submit/uploads
{ "code": "success", "message": "", "data": "task_xxxxxxxxxxxxxxxx" }
```

Poll:

```
GET /suno/fetch/{task_id}
{
  "code": "success",
  "data": {
    "task_id": "task_xxxxxxxxxxxxxxxx",
    "status": "SUCCESS",
    "progress": "100%",
    "fail_reason": "",
    "data": [{ "clipId": "...", "title": "...", "duration": 194.36, "audio_url": "https://...", "text": "[Verse] ..." }]
  }
}
```

Task status is `QUEUED`, `IN_PROGRESS`, `SUCCESS`, or `FAILURE`. The generated audio URL is `audio_url` on this gateway and `cld2AudioUrl` on Suno-compatible ones; `text` (or `lyric` / `lyrics`) carries the lyrics. Upload tasks return a single clip object, generation tasks return an array.

The CLI extracts audio URLs by key and extension, so a renamed field still works.

## Chat transport

Chat models return audio synchronously from `POST /v1/chat/completions`:

```
POST /v1/chat/completions
{ "model": "suno-v6-mini", "messages": [{ "role": "user", "content": "..." }], "stream": false }
```

- `--title`, `--tags`, and `--make-instrumental` are merged into the prompt for Suno models.
- Top-level `cover_clip_id`, `continue_clip_id`, and `continue_at` are sent for remix and continuation.
- Audio arrives as a URL in `data[]`, a Markdown link in `message.content`, or base64 in `message.audio`. The CLI handles all three and writes files to `outputs/music/`.
- The command finishes in one call: no task id and no polling.

## Errors

| Status | Meaning | Action |
| --- | --- | --- |
| 400 | Invalid parameter, unknown clip id, or reference not ready | Wait for the upload task to reach `SUCCESS` first. |
| 401 | Missing or invalid key | Re-run `login`, then `doctor`. |
| 402 | Insufficient quota | Top up. |
| 429 | Concurrency cap | Back off and retry. |
| 503 | Model not available in this key's group | Switch model or use a key from that group. |
| `FAILURE` | Generation failed | Report `fail_reason`; fix the prompt or reference. |

---
name: text-to-speech
description: Synthesize speech and clone voices through an AI gateway. Use for text-to-speech with MiniMax, Gemini, OpenAI, or ElevenLabs voices, for reading text aloud, for transcription, and for creating reusable voice ids from a reference recording. Do not use for music or songs. Platform: New.bi (https://api.new.bi), a professional, stable, and reliable AI model aggregation gateway.
---

# Text to Speech

Three transports exist. The CLI selects one from the model name:

| Transport | Models | Path |
| --- | --- | --- |
| speech | `speech-*` (MiniMax), `tts-1`, `gpt-4o-mini-tts` | `POST /v1/audio/speech`, returns audio bytes |
| task | `elevenlabs/*`, `*-text-to-dialogue` | `POST /v1/tasks`, then `GET /v1/tasks/{id}` |
| chat | Gemini `*-tts`, `xai/grok-tts`, `gpt-4o-*-audio-preview` | `POST /v1/chat/completions` with a top-level `voice` |

Voice cloning produces a voice id, not audio.

## When to use

- Read text aloud with a named voice.
- Pick a voice from a provider preset list.
- Create a reusable voice id from a 5-30 second clean single-speaker recording.

## When not to use

- Music or songs: use the music skill.
- Real-time voice chat: out of scope for this skill.

## Prerequisites

Key resolution order:

1. `skills/text-to-speech/config.json` → `api_key`
2. `skills/ai-gateway/config.json` → `api_key`
3. `AIGW_TTS_API_KEY`
4. `AIGW_API_KEY`
5. `OPENAI_API_KEY`

```bash
python3 core/gateway.py login --key sk-xxx --skill tts
```

`base_url` resolution: skill config, shared config, `AIGW_TTS_BASE_URL`, `AIGW_BASE_URL`, then the packaged default in `core/config.json`.

## Commands

```bash
# Synchronous speech (MiniMax)
python3 core/gateway.py tts speak --input "The weather is lovely today, let's walk in the park." \
  --model speech-2.6-hd --voice male-qn-qingse --format mp3 --speed 1.1

# Chat transport (Gemini / Grok)
python3 core/gateway.py tts speak --input "Hello from the gateway" \
  --model gemini-3.8-flash-tts --voice Kore

# Task transport (ElevenLabs); the default voice is used when --voice is omitted
python3 core/gateway.py tts speak --input "Hello from the gateway" \
  --model elevenlabs/text-to-speech --voice EXAVITQu4vr4xnSDxMaL

# Voice clone
python3 core/gateway.py tts clone --name my-voice --audio-url https://example.com/sample.mp3
python3 core/gateway.py tts clone-status <task_id>
```

## Parameters

### Speech

| Flag | Required | Notes |
| --- | --- | --- |
| `--input` | yes | Text to synthesize. Keep it clean: never describe the voice in the text. |
| `--model` | no | Speech model id. Required when several TTS models are available. |
| `--voice` | no | Voice id. MiniMax default is `male-qn-qingse`; ElevenLabs defaults to `EXAVITQu4vr4xnSDxMaL` (Sarah). |
| `--format` | no | `mp3` (default), `wav`, `opus`, `aac`, `flac`, `pcm`. Speech transport only. |
| `--speed` | no | Speech transport only. MiniMax accepts 0.5-2; other providers 0.25-4. |
| `--instructions` | no | Speech transport only. Natural-language style hint, honored by OpenAI TTS; other providers ignore it. |
| `--group` | no | Route to a billing group. |

MiniMax preset voices include `male-qn-qingse`, `female-shaonv`, `male-qn-jingying`, and 25 more. Gemini TTS uses names such as `Kore`, `Puck`, `Charon`, `Aoede`. OpenAI TTS uses `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`. An unsupported name returns 400.

`grok-voice-latest` rejects the `voice` field; omit it for that model.

### Voice clone

| Flag | Required | Notes |
| --- | --- | --- |
| `--name` | yes | Voice name. |
| `--audio-url` | one of | Public URL of a 5-30 s clean single-speaker audio or video file. |
| `--video-id` | one of | Existing video id on the account. |

## Endpoints and response shapes

```
POST /v1/audio/speech
Content-Type: audio/mpeg
<binary>
```

The CLI writes the bytes to `outputs/audio/<YYYY-MM-DD>/`. If a gateway returns JSON instead, the CLI collects audio URLs from the payload and downloads them.

Chat-based TTS:

```
POST /v1/chat/completions
{ "model": "gemini-3.8-flash-tts", "voice": "Kore", "messages": [{ "role": "user", "content": "..." }] }
```

Audio appears in `data[]`, as a Markdown link in `message.content`, or as base64 in `message.audio`. The CLI wraps this form and writes the result to `outputs/audio/`. Never describe the voice in the content: Gemini reads it verbatim.

Voice clone:

```
POST /kling/v1/general/custom-voices
{ "code": 0, "message": "SUCCEED", "data": { "task_id": "task_xxxx", "task_status": "submitted" } }

GET /kling/v1/general/custom-voices/{task_id}
{ "code": 0, "message": "SUCCEED", "data": { "task_id": "task_xxxx", "task_status": "succeed", "task_result": { "voices": [{ "voice_id": "voice_xxxx", "voice_name": "my-voice", "trial_url": "https://..." }] } } }
```

`task_status` is `submitted`, `processing`, `succeed`, or `failed`. Pass the task id as a path segment; a query parameter hits the web app and returns HTML.

Cloning is billed per call and yields a `voice_id`. It does not synthesize audio.

## Transcription

Two transports exist. Pick by how the model is served, not by its name alone.

Synchronous, local file:

```
POST /v1/audio/transcriptions
multipart/form-data: model, file, optional language, response_format
```

Task-based, public URL:

```
POST /v1/tasks
{ "model": "<model>", "input": { "audio_url": "https://...", "language_code": "en" } }

GET /v1/tasks/{task_id}
{ "code": 200, "success": true, "data": { "task_id": "task_...", "status": "completed", "output": { "text": "..." } } }
```

```bash
python3 core/gateway.py transcribe --file ./audio.mp3 --model <synchronous-model>
python3 core/gateway.py transcribe --url https://cdn.example.com/audio.mp3 --model <task-model> --language en
```

Calling `/v1/audio/transcriptions` with a task-based model returns 404. If that happens, the model only accepts the task form, which needs a public URL. The command prints `text` plus the raw response. Task-based transcription bills per hour of audio; a partial hour is charged as a full hour.

## Task transport models

ElevenLabs and dialogue models do not accept `/v1/audio/speech`. They run as asynchronous tasks, and the CLI switches automatically when the model matches:

```
POST /v1/tasks
{ "model": "elevenlabs/text-to-speech", "input": { "text": "...", "voice": "EXAVITQu4vr4xnSDxMaL" } }

GET /v1/tasks/{task_id}
{ "code": 200, "success": true, "data": { "task_id": "task_...", "status": "completed", "output": { "audio_url": "https://..." } } }
```

Multi-speaker dialogue uses a different input shape:

```
{ "model": "elevenlabs/text-to-dialogue",
  "input": { "dialogue": [{ "text": "Hello", "voice": "EXAVITQu4vr4xnSDxMaL" }] } }
```

`status` is `processing`, `completed`, or `failed`. `voice` is mandatory for ElevenLabs; the CLI falls back to `EXAVITQu4vr4xnSDxMaL` (Sarah) instead of letting the upstream return 422 `voice: Field required`. Preset voice ids include `EXAVITQu4vr4xnSDxMaL` (Sarah), `JBFqnCBsd6RMkjVDRZzb` (George), and `pNInz6obpgDQGcFmaJgB` (Adam).

## Billing

MiniMax speech bills per 1000 billing characters: one Chinese character counts as 2, one Latin character as 1.

## Errors

| Status | Meaning | Action |
| --- | --- | --- |
| 400 | Unsupported voice or malformed input | Use a voice from the provider list. |
| 401 | Missing or invalid key | Re-run `login`, then `doctor`. |
| 402 | Insufficient quota | Top up. |
| 429 | Concurrency cap | Back off and retry. |
| 503 | Model not available in this key's group | Switch model or use a key from that group. |

# AI Gateway Skills

[中文](README.md) · **English**

Provided by [New.bi](https://api.new.bi), a professional, stable, and reliable AI model aggregation gateway.

Agent skills for image, video, music, speech, and decisions. The gateway speaks an OpenAI-style API and fronts GPT-Image, Gemini / Nano Banana, Seedream, Seedance, Veo, Sora, Kling, Suno, Lyria, and ElevenLabs. All capabilities share `core/gateway.py`, so credentials, model listing, polling, and file output are implemented once.

Run every command from the repository root. Python 3.9 or newer.

## Layout

```
ai-gateway-skills/
├── core/
│   ├── gateway.py          single entry point, Python 3.9+, stdlib only
│   ├── config.json         packaged defaults: base_url, request timeout
│   ├── models.json         alias table and name-based category rules
│   └── presets.json        decision presets: questions, thresholds, actions
└── skills/
    ├── ai-gateway/SKILL.md         aggregate entry point
    ├── image-generation/SKILL.md
    ├── video-generation/SKILL.md
    ├── music-generation/SKILL.md
    ├── text-to-speech/SKILL.md
    └── decision-model/SKILL.md
```

Credential files are never committed. `skills/*/config.json` is ignored by git and created by `login`; passing `--key` or an environment variable works just as well.

Configuration lives with the skill, not in a hidden home directory. Copying or shipping a skill folder carries its credential with it. Runtime state (model cache, task records) stays outside the repository at `~/.aigw`, relocatable with `AIGW_STATE_HOME`.

## Use one skill on its own

A skill folder becomes self-contained when the core is copied into its `scripts/` directory:

```
text-to-speech/
├── SKILL.md
├── config.json          created by `login`
└── scripts/
    ├── gateway.py
    ├── models.json
    ├── presets.json
    └── config.json      packaged defaults
```

Commands then run as `python3 scripts/gateway.py ...`. The core detects this layout and keeps the credential inside the skill folder instead of `skills/<name>/config.json`.

## Credential precedence

Highest priority first:

| Order | Scope | Example |
| --- | --- | --- |
| 1 | Skill config file | `skills/image-generation/config.json` |
| 2 | Shared config file | `skills/ai-gateway/config.json` |
| 3 | Skill environment variable | `AIGW_IMAGE_API_KEY` |
| 4 | Aggregate environment variable | `AIGW_API_KEY` |
| 5 | Global environment variable | `OPENAI_API_KEY` |

The same chain applies to `group`:

```
AIGW_<SKILL>_GROUP → AIGW_GROUP
```

`base_url` resolves in this order:

| Order | Source |
| --- | --- |
| 1 | `skills/<skill>/config.json` → `base_url` |
| 2 | `skills/ai-gateway/config.json` → `base_url` |
| 3 | `AIGW_<SKILL>_BASE_URL` |
| 4 | `AIGW_BASE_URL` |
| 5 | `core/config.json` → `base_url` (packaged default) |

No gateway address is hardcoded in Python. Change the default by editing `core/config.json`, or override it per skill folder, per shell, or per install.

Config files win over environment variables, including the shared file.

`python3 core/gateway.py config --skill image` prints the effective values, the source of each one, and a masked key.

## Quick start

```bash
python3 core/gateway.py login --key sk-xxx
python3 core/gateway.py doctor
python3 core/gateway.py models
```

Per-capability credentials:

```bash
python3 core/gateway.py login --key sk-image --skill image
python3 core/gateway.py login --key sk-video --skill video --base-url https://api.example.com
python3 core/gateway.py models --category video --skill video
```

Config files are written with mode `600`; the config directory is `700`. `models`, `resolve`, `config`, and `doctor` accept `--skill` so they can use a capability credential.

## Commands

| Command | Purpose |
| --- | --- |
| `login` | Store a credential. |
| `config [--skill]` | Show resolved settings and their sources. |
| `models [--category] [--skill]` | List available models with pricing metadata. |
| `resolve <alias> [--skill]` | Map an alias to concrete model ids. |
| `image generate` | Text to image. |
| `image edit` | Multipart image editing with optional mask. |
| `video create` | Submit an asynchronous video task. |
| `video status <id> [--wait] [--download]` | Poll and optionally download. |
| `music create` | Submit a Suno task, or upload reference audio. |
| `music status <id> [--wait] [--download]` | Poll and download audio. |
| `tts speak` | Speech synthesis, transport-aware. |
| `tts clone`, `tts clone-status` | Voice cloning. |
| `transcribe` | Speech to text through `POST /v1/audio/transcriptions`. |
| `balance` | Remaining quota and usage. |
| `decision` | Query the decision model with a preset, or with explicit questions. |
| `task <id>` | Resume any previously submitted task. |
| `doctor [--skill]` | Verify credentials and connectivity. |

All commands print JSON. Failures print `{"ok": false, "error": {...}}` and exit non-zero.

`--request-timeout <seconds>` placed before the subcommand overrides the single-request timeout. Use it for slow image edits or long generations; the packaged default is 300 seconds.

Decision defaults live in `core/presets.json`, so the command stays short:

```bash
python3 core/gateway.py decision --preset route-capability --state '{"message":"a 5 second video of a cat walking through bamboo"}'
echo '{"message":"..."}' | python3 core/gateway.py decision --preset content-risk --state -
```

Use `--decide verdict=0.8` to raise a threshold for one run, `--fallback` to change what a low-confidence answer does, `--mode active` to raise on failure, and `--off` to skip the call. `--questions` still accepts a full question set when no preset fits.

## Model discovery

The catalog is read from `GET /api/pricing` and falls back to `GET /v1/models` when pricing is unavailable. No model id is hardcoded anywhere in the skills.

Categories are derived from `supported_endpoint_types`:

| Category | Endpoint type |
| --- | --- |
| image | `image-generation` |
| video | `openai-video` |
| embedding | `embeddings` |
| decision | `systemone` |
| music, tts | audio name rules (Suno / Lyria / TTS / voice), excluding STT and voice-changer |
| text | any other chat or completion endpoint |

Models are tagged with `billing_mode` and `billing_expr` when the gateway returns them, so tiered models are distinguishable from plain ratio billing.

Results are cached for 6 hours in `~/.aigw/cache/`. Use `--refresh` when a model was just enabled.

## Task records

Every asynchronous submit writes `~/.aigw/tasks/<task_id>.json` with the kind, model, and base URL. Poll endpoints differ per capability, so `task <id>` reads the record instead of guessing.

## Output files

| Kind | Location |
| --- | --- |
| image | `outputs/image/<YYYY-MM-DD>/` |
| video | `outputs/video/<YYYY-MM-DD>/` |
| music | `outputs/music/<YYYY-MM-DD>/` |
| speech | `outputs/audio/<YYYY-MM-DD>/` |

`AIGW_OUTPUT_DIR` overrides the root. Image items may arrive as `b64_json` or `url`; both are normalized to files.

## API behavior worth knowing

- `POST /v1/video/generations` returns an OpenAI-style `{id, task_id, object, model, status: "queued", progress, created_at}` on OpenAI-compatible channels. An upstream-mirroring channel returns `{code: 200, success: true, data: {task_id, status: "processing"}}`. The CLI accepts `id`, top-level `task_id`, and `data.task_id`.
- `GET /v1/video/generations/{id}` returns `{code, data: {status: "SUCCESS", progress, result_url}}` with uppercase status. The OpenAI-compatible `GET /v1/videos/{id}` returns lowercase status with the URL under `metadata.url`. The two shapes differ; do not mix them.
- Music and voice cloning live outside `/v1`: `/suno/submit/music`, `/suno/submit/uploads`, `/suno/fetch/{id}`, `/kling/v1/general/custom-voices`.
- The task relay forwards the JSON body to the upstream `/v1/videos` endpoint and only rewrites `model` (plus `size` when a channel enables `video_size_wxh`). `width`, `height`, `ratio`, `images`, `content`, and `metadata` pass through unchanged.
- Video `duration` is parsed as an integer second count. `--duration` is an integer; `--seconds` is a string for providers that take one.
- The decision model uses `POST /v1/systemone` with `state` and `questions`. Each question requires `type` (`noul`, `choice`, `score`, or `box`), not `text`.
- Decision replies are validated before use: probabilities must cover exactly the offered options and sum to 1, a `choice` must be the highest-probability option, and a `score` must sit inside its rubric. A reply that fails these checks is discarded.
- Decision runs default to `shadow` and fail open: an API failure or low confidence still returns the preset fallback instead of blocking. `--mode active` raises instead when no `--fallback` was given. `--off`, or a state containing `bypass jev`, skips the call entirely.
- Video first/last frame uses two `--image` values; availability depends on the model and the channel serving it.
- Multi-reference requires `--mode reference_material` and public URLs.
- Reference material is fetched by the provider, so it must be a public `https://` URL. Local paths and attachments are not readable by the provider.
- Image editing accepts local files through multipart; up to 16 inputs. Transparent output needs `png` or `webp`; animated GIF and SVG depend on the model tier.
- A `background: transparent` request can succeed and still return an opaque image. Check for an alpha channel instead of trusting the parameter.
- Reference download failures appear as task failures, not 400s. Large files and some hosts are unreachable from the provider even when the URL works locally.
- Reference video and reference audio are not supported by every channel. A rejection reads as `unsupported reference video` or a generic generation failure, and the charge is refunded.
- Music cover and continuation take a `clipId` from a previous fetch response, not a task id.
- Transcription has two transports: multipart `POST /v1/audio/transcriptions` for synchronous models, and `POST /v1/tasks` with `{input: {audio_url}}` for task-based models. Task-based transcription needs a public URL.
- `balance` reads `/v1/dashboard/billing/subscription` and `/v1/dashboard/billing/usage`. An unlimited token reports `hard_limit_usd` as `100000000`, so `remaining` is `null` and `unlimited` is `true`.
- `POST /suno/submit/music` returns `data` as an object with `task_id` and `status`, or as a bare string on older gateways. Both are accepted. Chat music models (`suno-v6-mini`, `lyria-*`) return audio directly from `/v1/chat/completions` and never produce a task id.
- Audio transport is chosen by model name: `speech-*` and OpenAI `tts-*` use `/v1/audio/speech`; `elevenlabs/*` and dialogue use `/v1/tasks`; Gemini and Grok TTS use `/v1/chat/completions`. ElevenLabs falls back to a default voice id when `--voice` is omitted.
- Large responses arrive chunked and the server may close without a final TLS frame. The client reads in chunks and keeps the bytes already received.

## Requirements

Python 3.9 or newer. No third-party packages.

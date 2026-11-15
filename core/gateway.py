#!/usr/bin/env python3
"""Shared core for AI gateway skills: credentials, model discovery, relay calls.

New.bi（https://api.new.bi），专业、稳定、可靠的大模型聚合中转平台。
New.bi is a professional, stable, and reliable AI model aggregation gateway.
Repository: https://github.com/tokenservice/ai-gateway-skills
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import http.client
import json
import math
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent
CORE_CONFIG_PATH = CORE_DIR / "config.json"

PLATFORM = "New.bi"
PLATFORM_URL = "https://api.new.bi"
PLATFORM_TAGLINE = "专业、稳定、可靠的大模型聚合中转平台"
PLATFORM_DESC_ZH = "New.bi，专业、稳定、可靠的大模型聚合中转平台。"
PLATFORM_DESC_EN = "New.bi is a professional, stable, and reliable AI model aggregation gateway."
REPO_URL = "https://github.com/tokenservice/ai-gateway-skills"
STATE_DIR = Path(os.environ.get("AIGW_STATE_HOME", Path.home() / ".aigw"))
OUTPUT_DIR = Path(os.environ.get("AIGW_OUTPUT_DIR", Path.cwd() / "outputs"))
CACHE_TTL_SECONDS = 6 * 3600
TERMINAL_STATUS = {"SUCCESS", "FAILURE", "FAILED", "COMPLETED", "CANCELLED", "CANCELED"}
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

SKILL_DIRS = {
    "image": "image-generation",
    "video": "video-generation",
    "music": "music-generation",
    "tts": "text-to-speech",
    "decision": "decision-model",
}
SHARED_SKILL_DIR = "ai-gateway"

CATEGORY_BY_ENDPOINT = {
    "image-generation": "image",
    "openai-video": "video",
    "embeddings": "embedding",
    "systemone": "decision",
}

SKILL_BY_COMMAND = {
    "image": "image",
    "video": "video",
    "music": "music",
    "tts": "tts",
    "transcribe": "tts",
    "decision": "decision",
}

AUDIO_EXCLUDED = (
    "speech-to-text", "voice-changer", "speech-to-speech",
    "custom-voice", "voice-design", "suno_uploads", "suno_lyrics",
)
AUDIO_SFX_KEYWORDS = ("sfx", "sound-effect", "sound_effect", "foley")
AUDIO_TTS_KEYWORDS = (
    "tts", "text-to-speech", "text_to_speech", "voice", "speech",
    "dialogue", "audio-preview", "gpt-4o-audio",
)
AUDIO_MUSIC_KEYWORDS = (
    "suno", "lyria", "music", "chirp", "udio", "ace-step", "riffusion",
    "song", "melody",
)
LEGACY_TASK_MUSIC = ("suno_music", "chirp", "music-", "mureka")
SUNO_CHAT_VERSION = re.compile(r"suno[-_ ]?v?[6-9]")
DEFAULT_ELEVENLABS_VOICE = "EXAVITQu4vr4xnSDxMaL"


class GatewayError(Exception):
    def __init__(self, message: str, status: int | None = None, code: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class NetworkError(GatewayError):
    pass


class DecisionInvalid(GatewayError):
    """A reply that parsed but contradicts itself, so it must not be acted on."""


QUESTION_TYPES = ("choice", "score", "noul", "box")
MAX_CHOICE_OPTIONS = 255
MAX_SCORE_LEVELS = 10
MAX_STATE_CHARS = 60000
PROBABILITY_TOLERANCE = 1e-6
ARGMAX_TOLERANCE = 1e-6


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def fail(code: str, message: str, status: int | None = None) -> None:
    error = {"code": code, "message": message}
    if status is not None:
        error["status"] = status
    emit({"ok": False, "error": error})
    sys.exit(1)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def normalize_skill(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "", (name or "").strip().lower())


def packaged_defaults() -> dict:
    return _read_json(CORE_CONFIG_PATH)


def skill_config_path(skill: str | None) -> Path:
    if CORE_DIR.name == "scripts" and (CORE_DIR.parent / "SKILL.md").is_file():
        return CORE_DIR.parent / "config.json"
    directory = SKILL_DIRS.get(skill or "", SHARED_SKILL_DIR)
    return CORE_DIR.parent / "skills" / directory / "config.json"


def resolve_settings(skill: str | None) -> dict:
    skill = normalize_skill(skill or "") or None
    files = []
    if skill:
        files.append(skill_config_path(skill))
    if skill != SHARED_SKILL_DIR:
        files.append(skill_config_path(None))

    env_keys = []
    env_urls = []
    env_groups = []
    if skill:
        env_keys.append(f"AIGW_{skill.upper()}_API_KEY")
        env_urls.append(f"AIGW_{skill.upper()}_BASE_URL")
        env_groups.append(f"AIGW_{skill.upper()}_GROUP")
    env_keys.extend(["AIGW_API_KEY", "OPENAI_API_KEY"])
    env_urls.append("AIGW_BASE_URL")
    env_groups.append("AIGW_GROUP")

    settings = {"api_key": "", "base_url": "", "group": "", "sources": {}}
    for path in files:
        data = _read_json(path)
        for field in ("api_key", "base_url", "group"):
            if not settings[field] and isinstance(data.get(field), str) and data[field]:
                settings[field] = data[field]
                settings["sources"][field] = str(path)
    for name in env_keys:
        if not settings["api_key"] and os.environ.get(name):
            settings["api_key"] = os.environ[name]
            settings["sources"]["api_key"] = name
    for name in env_urls:
        if not settings["base_url"] and os.environ.get(name):
            settings["base_url"] = os.environ[name]
            settings["sources"]["base_url"] = name
    for name in env_groups:
        if not settings["group"] and os.environ.get(name):
            settings["group"] = os.environ[name]
            settings["sources"]["group"] = name

    defaults = packaged_defaults()
    if not settings["base_url"] and isinstance(defaults.get("base_url"), str) and defaults["base_url"]:
        settings["base_url"] = defaults["base_url"]
        settings["sources"]["base_url"] = str(CORE_CONFIG_PATH)

    timeout = defaults.get("request_timeout_seconds")
    settings["timeout"] = int(timeout) if isinstance(timeout, (int, float)) and timeout > 0 else 180
    settings["base_url"] = (settings["base_url"] or "").rstrip("/")
    settings["skill"] = skill or ""
    return settings


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _parse_error(body: bytes, status: int) -> tuple[str, str]:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return body.decode("utf-8", "replace")[:500] or f"HTTP {status}", ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error), str(error.get("code") or "")
        if isinstance(error, str) and error:
            return error, str(payload.get("code") or "")
        for key in ("message", "msg", "detail"):
            if payload.get(key):
                return str(payload[key]), str(payload.get("code") or "")
    return json.dumps(payload, ensure_ascii=False)[:500], ""


def _read_body(resp) -> bytes:
    chunks = []
    while True:
        try:
            chunk = resp.read(65536)
        except ssl.SSLEOFError:
            break
        except http.client.IncompleteRead as err:
            if err.partial:
                chunks.append(err.partial)
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def request(
    settings: dict,
    method: str,
    path: str,
    body: dict | None = None,
    query: dict | None = None,
    fields: list | None = None,
    files: list | None = None,
    timeout: int | None = None,
) -> tuple[int, dict, bytes]:
    if not settings.get("base_url"):
        raise GatewayError(
            "base_url is not configured: use `login --base-url`, set AIGW_BASE_URL, or edit core/config.json"
        )
    url = settings["base_url"] + path
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)

    request_timeout = timeout or settings.get("timeout", 180)
    headers = {"Accept": "application/json", "Connection": "close", "User-Agent": USER_AGENT}
    data = None
    if files is not None:
        data, content_type = _encode_multipart(fields or [], files)
        headers["Content-Type"] = content_type
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if settings.get("api_key"):
        headers["Authorization"] = f"Bearer {settings['api_key']}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=request_timeout) as resp:
            return resp.status, dict(resp.headers), _read_body(resp)
    except urllib.error.HTTPError as err:
        raw = _read_body(err)
        message, code = _parse_error(raw, err.code)
        raise GatewayError(message, err.code, code) from None
    except urllib.error.URLError as err:
        raise NetworkError(f"{url}: {err.reason}") from None


def request_json(settings: dict, method: str, path: str, body: dict | None = None, query: dict | None = None) -> dict:
    _, _, raw = request(settings, method, path, body=body, query=query)
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise GatewayError("upstream returned a non-JSON body") from None
    if not isinstance(payload, dict):
        raise GatewayError("upstream returned an unexpected JSON payload")
    return payload


def _encode_multipart(fields: list, files: list) -> tuple[bytes, str]:
    boundary = f"----aigw{int(time.time() * 1000)}{os.getpid()}"
    chunk = []
    for name, value in fields:
        chunk.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
    for name, filename, payload, content_type in files:
        header = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n"
        )
        chunk.append(header.encode("utf-8"))
        chunk.append(payload)
        chunk.append(b"\r\n")
    chunk.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunk), f"multipart/form-data; boundary={boundary}"


def models_config() -> dict:
    return _read_json(CORE_DIR / "models.json")


def audio_kind(model_id: str) -> str:
    name = model_id.lower()
    if any(keyword in name for keyword in AUDIO_EXCLUDED):
        return ""
    if any(keyword in name for keyword in AUDIO_SFX_KEYWORDS):
        return "sfx"
    if any(keyword in name for keyword in AUDIO_TTS_KEYWORDS):
        return "tts"
    if any(keyword in name for keyword in AUDIO_MUSIC_KEYWORDS):
        return "music"
    return ""


def audio_transport(model_id: str) -> str:
    name = model_id.lower()
    if name.startswith("speech-"):
        return "speech"
    if "elevenlabs" in name or "dialogue" in name:
        return "task"
    if ("gpt-4o" in name or name.startswith("tts-")) and "audio" not in name:
        return "speech"
    if "suno" in name:
        return "chat" if SUNO_CHAT_VERSION.search(name) else "task"
    if any(keyword in name for keyword in LEGACY_TASK_MUSIC):
        return "task"
    return "chat"


def classify_model(model_id: str, endpoint_types: list | None, patterns: dict) -> str:
    for endpoint, category in CATEGORY_BY_ENDPOINT.items():
        if endpoint_types and endpoint in endpoint_types:
            return category
    name = model_id.lower()
    if any(keyword in name for keyword in AUDIO_EXCLUDED):
        return "text"
    kind = audio_kind(name)
    if kind == "music":
        return "music"
    if kind in ("tts", "sfx"):
        return "tts"
    for category in ("video", "music", "tts", "decision", "image"):
        for pattern in patterns.get(category, []):
            if fnmatch.fnmatch(name, pattern.lower()):
                return category
    return "text"


def _cache_path(settings: dict) -> Path:
    key = re.sub(r"[^a-z0-9]+", "-", (settings.get("base_url") or "unconfigured").lower()).strip("-")
    return STATE_DIR / "cache" / f"models-{key}.json"


def fetch_models(settings: dict, refresh: bool = False) -> dict:
    cache = _cache_path(settings)
    cached = _read_json(cache)
    if not refresh and cached.get("fetched_at", 0) + CACHE_TTL_SECONDS > time.time():
        return cached

    patterns = models_config().get("patterns", {})
    models = []
    source = ""
    error = ""
    try:
        payload = request_json(settings, "GET", "/api/pricing")
        for item in payload.get("data") or []:
            if not isinstance(item, dict) or not item.get("model_name"):
                continue
            endpoints = item.get("supported_endpoint_types") or []
            models.append({
                "id": item["model_name"],
                "category": classify_model(item["model_name"], endpoints, patterns),
                "endpoint_types": endpoints,
                "quota_type": item.get("quota_type"),
                "price": item.get("model_price"),
                "ratio": item.get("model_ratio"),
                "billing_mode": item.get("billing_mode"),
                "billing_expr": item.get("billing_expr"),
                "billing_unit": item.get("billing_unit"),
                "billing_unit_price": item.get("billing_unit_price"),
                "groups": item.get("enable_groups") or [],
            })
        source = "pricing"
        if not models:
            error = "pricing returned no models"
    except GatewayError as err:
        error = f"{err.status or ''} {err.message}".strip()

    if not models:
        payload = request_json(settings, "GET", "/v1/models")
        for item in payload.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                models.append({
                    "id": item["id"],
                    "category": classify_model(item["id"], None, patterns),
                    "endpoint_types": [],
                    "groups": [],
                })
        source = "models"

    result = {"fetched_at": int(time.time()), "source": source, "error": error, "models": models}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False), "utf-8")
    return result


def resolve_alias(alias: str, models: list) -> list:
    key = alias.lower().strip()
    for model in models:
        if model["id"].lower() == key:
            return [model]
    patterns = models_config().get("aliases", {}).get(key, [])
    matches = []
    for pattern in patterns:
        for model in models:
            if fnmatch.fnmatch(model["id"].lower(), pattern.lower()) and model not in matches:
                matches.append(model)
    return matches


def pick_model(args, models: list, category: str, alias: str = "") -> str:
    if args_model := getattr(args, "model", ""):
        return args_model
    if alias:
        matches = resolve_alias(alias, models)
        if matches:
            return matches[0]["id"]
    candidates = [m["id"] for m in models if m["category"] == category]
    if len(candidates) == 1:
        return candidates[0]
    hint = f", alias '{alias}'" if alias else ""
    raise GatewayError(f"model is required: pass --model or make the alias unique ({category}{hint})")


def slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5]+", "-", text or "").strip("-")
    return (cleaned[:limit] or "output").lower()


def sniff_extension(payload: bytes, fallback: str = "bin") -> str:
    if payload.startswith(b"\x89PNG"):
        return "png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "webp"
    if payload[:3] == b"GIF":
        return "gif"
    if payload[4:8] == b"ftyp":
        return "mp4"
    if payload[:3] == b"ID3":
        return "mp3"
    if payload[:4] == b"fLaC":
        return "flac"
    if payload[:4] == b"OggS":
        return "ogg"
    return fallback


def save_bytes(category: str, stem: str, payload: bytes, extension: str = "") -> Path:
    target = OUTPUT_DIR / category / date.today().isoformat()
    target.mkdir(parents=True, exist_ok=True)
    ext = extension or sniff_extension(payload)
    base = f"{stem}-{datetime.now().strftime('%H%M%S')}"
    path = target / f"{base}.{ext.lstrip('.')}"
    index = 2
    while path.exists():
        path = target / f"{base}-{index}.{ext.lstrip('.')}"
        index += 1
    path.write_bytes(payload)
    return path


def download(settings: dict, url: str, timeout: int = 120) -> bytes:
    for authorized in (False, True):
        headers = {"Accept": "*/*", "Connection": "close", "User-Agent": USER_AGENT}
        if authorized:
            if not settings.get("api_key"):
                break
            headers["Authorization"] = f"Bearer {settings['api_key']}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _read_body(resp)
        except urllib.error.HTTPError as err:
            if err.code in (401, 403) and not authorized:
                continue
            raise GatewayError(f"download failed: HTTP {err.code}", err.code) from None
        except urllib.error.URLError as err:
            raise NetworkError(f"{url}: {err.reason}") from None
    raise GatewayError("download failed: access denied", 403)


def task_record_path(task_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", task_id)
    return STATE_DIR / "tasks" / f"{safe}.json"


def save_task(record: dict) -> Path:
    path = task_record_path(record["task_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return path


def load_task(task_id: str) -> dict:
    return _read_json(task_record_path(task_id))


def normalize_video(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict) and ("status" in data or "task_id" in data):
        return {
            "status": str(data.get("status") or "").upper(),
            "progress": data.get("progress"),
            "url": data.get("result_url") or data.get("url") or "",
            "reason": data.get("fail_reason") or "",
        }
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    return {
        "status": str(payload.get("status") or "").upper(),
        "progress": payload.get("progress"),
        "url": str(metadata.get("url") or ""),
        "reason": str(error.get("message") or ""),
    }


def normalize_music(payload: dict) -> dict:
    data = payload.get("data")
    if not isinstance(data, dict):
        return {"status": "", "progress": None, "urls": [], "reason": ""}
    return {
        "status": str(data.get("status") or "").upper(),
        "progress": data.get("progress"),
        "urls": collect_audio_urls(data.get("data")),
        "reason": str(data.get("fail_reason") or ""),
    }


AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac", ".opus", ".webm")
AUDIO_KEYS = {"cld2audiourl", "audio_url", "audiourl", "stream_audio_url", "source_audio_url"}
URL_PATTERN = re.compile(r"https?://[^\s)<>\"']+")


def collect_audio_urls(node) -> list:
    found = []

    def walk(value, key=""):
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str) and value.startswith(("http://", "https://")):
            lowered = key.lower()
            bare = value.lower().split("?", 1)[0]
            if lowered in AUDIO_KEYS or bare.endswith(AUDIO_EXTENSIONS):
                if value not in found:
                    found.append(value)

    walk(node)
    return found


def collect_chat_audio(payload: dict) -> tuple[list, list]:
    urls = []
    inline = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        mime = str(item.get("mime_type") or "")
        if url and (mime.startswith("audio/") or url.lower().split("?", 1)[0].endswith(AUDIO_EXTENSIONS)):
            if url not in urls:
                urls.append(url)

    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    if not isinstance(message, dict):
        message = {}

    audio = message.get("audio")
    if isinstance(audio, dict) and isinstance(audio.get("data"), str) and audio["data"]:
        inline.append((base64.b64decode(audio["data"]), str(audio.get("format") or "mp3")))

    content = message.get("content")
    if isinstance(content, list):
        content = "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    if isinstance(content, str):
        for url in URL_PATTERN.findall(content):
            if url.lower().split("?", 1)[0].endswith(AUDIO_EXTENSIONS) and url not in urls:
                urls.append(url)
    return urls, inline


def request_chat_audio(settings: dict, model: str, prompt: str, voice: str = "",
                       group: str = "", extra: dict | None = None) -> tuple[list, list]:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    if voice:
        body["voice"] = voice
    if group:
        body["group"] = group
    if extra:
        body.update(extra)
    payload = request_json(settings, "POST", "/v1/chat/completions", body=body)
    urls, inline = collect_chat_audio(payload)
    if not urls and not inline:
        raise GatewayError(f"response contained no audio data: {json.dumps(payload, ensure_ascii=False)[:300]}")
    return urls, inline


def save_chat_audio(category: str, stem: str, urls: list, inline: list, settings: dict) -> tuple[list, list]:
    files = []
    for index, (payload, extension) in enumerate(inline):
        files.append(str(save_bytes(category, f"{stem}-{index + 1}", payload, extension)))
    for index, url in enumerate(urls):
        path = save_bytes(category, f"{stem}-{len(inline) + index + 1}", download(settings, url))
        files.append(str(path))
    return files, urls


def poll(settings: dict, path: str, normalize, timeout: int, interval: int) -> dict:
    deadline = time.time() + max(timeout, 1)
    interval = max(interval, 1)
    while True:
        try:
            payload = request_json(settings, "GET", path)
        except NetworkError:
            if time.time() >= deadline:
                raise
            time.sleep(interval)
            continue
        state = normalize(payload)
        if state["status"] in TERMINAL_STATUS or time.time() >= deadline:
            return {"payload": payload, "state": state}
        time.sleep(interval)


def build_body(args, fields: list) -> dict:
    body = {}
    for field in fields:
        value = getattr(args, field, None)
        if value is None or value == "" or value == []:
            continue
        body[field] = value
    if getattr(args, "group", ""):
        body["group"] = args.group
    return body


def handle_login(args, settings: dict) -> None:
    if not args.key:
        raise GatewayError("--key is required")
    raw_skill = (args.skill or "").strip().lower()
    skill = normalize_skill(raw_skill)
    if raw_skill and raw_skill != skill:
        raise GatewayError("--skill must contain only letters, digits, dashes, or underscores")
    if args.base_url and not args.base_url.startswith(("http://", "https://")):
        raise GatewayError("--base-url must start with http:// or https://")
    target = skill_config_path(skill or None)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _read_json(target)
    data["api_key"] = args.key
    if args.base_url:
        data["base_url"] = args.base_url.rstrip("/")
    if getattr(args, "group", ""):
        data["group"] = args.group
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.chmod(target, 0o600)
    emit({
        "ok": True,
        "config": str(target),
        "base_url": data.get("base_url") or settings["base_url"],
    })


def handle_config(args, settings: dict) -> None:
    skill = settings["skill"] or None
    emit({
        "ok": True,
        "skill": settings["skill"] or "shared",
        "platform": {"name": PLATFORM, "url": PLATFORM_URL, "tagline": PLATFORM_TAGLINE,
                     "description_zh": PLATFORM_DESC_ZH, "description_en": PLATFORM_DESC_EN,
                     "repository": REPO_URL},
        "config": str(skill_config_path(skill)),
        "base_url": settings["base_url"],
        "group": settings["group"],
        "api_key": mask_secret(settings["api_key"]),
        "sources": settings["sources"],
        "state_dir": str(STATE_DIR),
        "core_config": str(CORE_CONFIG_PATH),
    })


def handle_models(args, settings: dict) -> None:
    result = fetch_models(settings, refresh=args.refresh)
    models = result["models"]
    if args.category and args.category != "all":
        models = [m for m in models if m["category"] == args.category]
    counts = {}
    for model in result["models"]:
        counts[model["category"]] = counts.get(model["category"], 0) + 1
    emit({
        "ok": True,
        "base_url": settings["base_url"],
        "source": result["source"],
        "fallback_reason": result["error"],
        "count": len(models),
        "counts": counts,
        "models": models,
    })


def handle_resolve(args, settings: dict) -> None:
    result = fetch_models(settings)
    matches = resolve_alias(args.alias, result["models"])
    if not matches:
        raise GatewayError(f"no model matches alias '{args.alias}'")
    emit({"ok": True, "alias": args.alias, "matches": matches})


def _persist_images(settings: dict, payload: dict, stem: str, fmt: str) -> tuple[list, list]:
    saved, urls = [], []
    items = payload.get("data")
    if not isinstance(items, list):
        return saved, urls
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        encoded = item.get("b64_json")
        url = str(item.get("url") or "").strip()
        if encoded:
            raw = base64.b64decode(encoded.split(",", 1)[-1])
            path = save_bytes("image", f"{stem}-{index + 1}", raw, fmt)
            saved.append(str(path))
        elif url:
            try:
                raw = download(settings, url)
                path = save_bytes("image", f"{stem}-{index + 1}", raw, fmt)
                saved.append(str(path))
            except GatewayError:
                urls.append(url)
    return saved, urls


def handle_image_generate(args, settings: dict) -> None:
    model = pick_model(args, fetch_models(settings)["models"], "image", "gpt-image")
    body = build_body(args, ["prompt", "size", "n", "quality", "output_format", "background", "moderation",
                             "complexity", "output_compression", "frame_count", "frame_duration_ms"])
    body["model"] = model
    if not body.get("prompt"):
        raise GatewayError("--prompt is required")
    _, _, raw = request(settings, "POST", "/v1/images/generations", body=body)
    payload = json.loads(raw.decode("utf-8", "replace"))
    saved, urls = _persist_images(settings, payload, slug(args.prompt), body.get("output_format", ""))
    if not saved and not urls:
        raise GatewayError(f"response contained no image data: {json.dumps(payload, ensure_ascii=False)[:300]}")
    emit({"ok": True, "model": model, "files": saved, "urls": urls, "created": payload.get("created")})


def handle_image_edit(args, settings: dict) -> None:
    if not args.image:
        raise GatewayError("--image is required (repeatable)")
    model = pick_model(args, fetch_models(settings)["models"], "image", "gpt-image")
    fields = [("model", model), ("prompt", args.prompt)]
    for name in ("size", "quality", "output_format", "background", "moderation", "n", "output_compression", "complexity"):
        value = getattr(args, name, None)
        if value not in (None, ""):
            fields.append((name, str(value)))
    if args.group:
        fields.append(("group", args.group))
    files = []
    for path in args.image:
        try:
            data = Path(path).read_bytes()
        except OSError as err:
            raise GatewayError(f"cannot read image {path}: {err.strerror or err}") from None
        files.append(("image[]", Path(path).name, data, "application/octet-stream"))
    if args.mask:
        try:
            mask = Path(args.mask).read_bytes()
        except OSError as err:
            raise GatewayError(f"cannot read mask {args.mask}: {err.strerror or err}") from None
        files.append(("mask", Path(args.mask).name, mask, "application/octet-stream"))
    if args.markup:
        try:
            markup = Path(args.markup).read_bytes()
        except OSError as err:
            raise GatewayError(f"cannot read markup {args.markup}: {err.strerror or err}") from None
        files.append(("markup", Path(args.markup).name, markup, "application/octet-stream"))
    _, _, raw = request(settings, "POST", "/v1/images/edits", fields=fields, files=files)
    payload = json.loads(raw.decode("utf-8", "replace"))
    saved, urls = _persist_images(settings, payload, slug(args.prompt), args.output_format or "")
    if not saved and not urls:
        raise GatewayError(f"response contained no image data: {json.dumps(payload, ensure_ascii=False)[:300]}")
    emit({"ok": True, "model": model, "files": saved, "urls": urls, "created": payload.get("created")})


def handle_video_create(args, settings: dict) -> None:
    model = pick_model(args, fetch_models(settings)["models"], "video", "seedance")
    body = build_body(args, ["prompt", "duration", "seconds", "size", "mode", "ratio", "width", "height"])
    body["model"] = model
    name = model.lower()
    is_h3 = name.startswith("minimax-h3")
    is_vidu = name.startswith("vidu")
    is_kling4 = name.startswith("kling-4")
    is_omni = name.startswith("gemini-omni")
    if is_h3 and body.get("size"):
        body["size"] = str(body["size"]).upper()

    images = list(args.image) + list(args.images)
    reference_videos = list(args.reference_video)
    reference_audios = list(args.reference_audio)
    metadata = load_json_argument(args.metadata) if args.metadata else {}
    if not isinstance(metadata, dict):
        metadata = {}
    content = load_json_argument(args.content) if args.content else None

    if args.ratio:
        body["ratio"] = args.ratio
        metadata.setdefault("aspect_ratio", args.ratio)
    if args.audio:
        metadata["audio"] = True
    if is_h3:
        body.setdefault("ratio", metadata.get("aspect_ratio") or "16:9")
        metadata.setdefault("aspect_ratio", body["ratio"])

    reference_mode = body.get("mode") in ("reference_material", "reference_images", "r2v")
    if is_vidu and name.startswith("vidu-q4") and not images and not reference_videos and not reference_audios:
        raise GatewayError("Vidu Q4 requires at least one image")
    if reference_mode:
        if is_vidu:
            if reference_audios:
                body["mode"] = "reference_material"
                body["audio_urls"] = reference_audios
            else:
                body["mode"] = "reference_images"
        elif is_omni:
            body["mode"] = "r2v"
        else:
            body["mode"] = "reference_material"
    elif is_omni:
        body["mode"] = "r2v" if images else "t2v"

    if images or reference_videos or reference_audios:
        if reference_mode:
            if images:
                body["images"] = images
                metadata["reference_image_urls"] = images
            if reference_videos:
                metadata["reference_video_urls"] = reference_videos
            if reference_audios:
                metadata["reference_audio_urls"] = reference_audios
            if content is None:
                content = [{"type": "text", "text": body.get("prompt", "")}]
                content += [{"type": "image_url", "image_url": {"url": url}, "role": "reference_image"}
                            for url in images]
                content += [{"type": "video_url", "video_url": {"url": url}, "role": "reference_video"}
                            for url in reference_videos]
                content += [{"type": "audio_url", "audio_url": {"url": url}, "role": "reference_audio"}
                            for url in reference_audios]
        elif images:
            if len(images) > 1 and is_h3:
                raise GatewayError(
                    "MiniMax H3 does not support first/last frames; pass --mode reference_material for image references"
                )
            if len(images) > 1 and is_vidu and name.startswith("vidu-q4"):
                raise GatewayError(
                    "Vidu Q4 does not support first/last frames; pass --mode reference_images"
                )
            if len(images) == 1:
                body["image"] = images[0]
                metadata["first_frame_image"] = images[0]
            else:
                body["image"] = images[0]
                body["images"] = images
                metadata["first_frame_image"] = images[0]
                metadata["last_frame_image"] = images[1]
                metadata["image_tail"] = images[1]
                if is_kling4:
                    body["mode"] = "i2v_first_last"

            if is_h3:
                content = [{"type": "text", "text": body.get("prompt", "")},
                           {"type": "image_url", "image_url": {"url": images[0]}, "role": "first_frame"}]
                if len(images) > 1:
                    content.append({"type": "image_url", "image_url": {"url": images[1]}, "role": "last_frame"})

    if metadata:
        body["metadata"] = metadata
    if content is not None:
        body["content"] = content
    if not body.get("prompt") and not body.get("content"):
        raise GatewayError("--prompt or --content is required")
    _, _, raw = request(settings, "POST", "/v1/video/generations", body=body)
    payload = json.loads(raw.decode("utf-8", "replace"))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    task_id = payload.get("id") or payload.get("task_id") or data.get("task_id")
    if not task_id:
        raise GatewayError(f"missing task id in response: {json.dumps(payload, ensure_ascii=False)[:300]}")
    record = {
        "task_id": task_id,
        "kind": "video",
        "model": model,
        "group": args.group or settings["group"],
        "base_url": settings["base_url"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_task(record)
    emit({"ok": True, "task_id": task_id, "status": payload.get("status") or "queued", "model": model})


def handle_video_status(args, settings: dict) -> None:
    task_id = urllib.parse.quote(args.task_id, safe="")
    path = f"/v1/video/generations/{task_id}"
    if args.wait:
        result = poll(settings, path, normalize_video, args.timeout, args.interval)
        state = result["state"]
    else:
        state = normalize_video(request_json(settings, "GET", path))

    files = []
    if state["status"] == "SUCCESS" and args.download:
        if state["url"]:
            raw = download(settings, state["url"])
        else:
            _, _, raw = request(settings, "GET", f"/v1/videos/{task_id}/content")
        files.append(str(save_bytes("video", slug(args.task_id, 24), raw, "mp4")))

    emit({"ok": True, "task_id": args.task_id, "status": state["status"], "progress": state["progress"],
          "url": state["url"], "reason": state["reason"], "files": files})


def submit_task_id(payload: dict) -> str:
    data = payload.get("data")
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return str(data.get("task_id") or "")
    return ""


def handle_music_create(args, settings: dict) -> None:
    if args.upload_url:
        body = {"model": args.model or "suno_uploads", "url": args.upload_url}
        if args.group:
            body["group"] = args.group
        payload = request_json(settings, "POST", "/suno/submit/uploads", body=body)
        task_id = submit_task_id(payload)
        if not task_id:
            raise GatewayError("missing upload task id in response")
        save_task({"task_id": task_id, "kind": "music", "action": "uploads",
                   "model": body["model"], "base_url": settings["base_url"],
                   "created_at": datetime.now().isoformat(timespec="seconds")})
        emit({"ok": True, "task_id": task_id, "action": "upload"})
        return

    model = pick_model(args, fetch_models(settings)["models"], "music", "suno")
    if not args.prompt:
        raise GatewayError("--prompt is required")

    if audio_transport(model) == "chat":
        prompt = args.prompt
        if "suno" in model.lower():
            lines = []
            if args.title:
                lines.append(f"Title: {args.title}")
            if args.tags:
                lines.append(f"Style: {args.tags}")
            if args.make_instrumental:
                lines.append("Instrumental only, no vocals, no lyrics.")
            if lines:
                prompt = "\n".join(lines + [prompt])
        extra = {}
        if args.cover_clip_id:
            extra["cover_clip_id"] = args.cover_clip_id
        if args.continue_clip_id:
            extra["continue_clip_id"] = args.continue_clip_id
            if args.continue_at is not None:
                extra["continue_at"] = args.continue_at
        urls, inline = request_chat_audio(settings, model, prompt, group=args.group, extra=extra)
        files, urls = save_chat_audio("music", slug(prompt), urls, inline, settings)
        emit({"ok": True, "model": model, "files": files, "urls": urls})
        return

    body = build_body(args, ["prompt", "title", "tags", "make_instrumental", "task_id",
                             "cover_clip_id", "continue_clip_id", "continue_at"])
    body["model"] = model
    payload = request_json(settings, "POST", "/suno/submit/music", body=body)
    task_id = submit_task_id(payload)
    if not task_id:
        raise GatewayError(f"missing task id in response: {json.dumps(payload, ensure_ascii=False)[:300]}")
    save_task({"task_id": task_id, "kind": "music", "model": model,
               "base_url": settings["base_url"],
               "created_at": datetime.now().isoformat(timespec="seconds")})
    data = payload.get("data")
    status = data.get("status") if isinstance(data, dict) else "QUEUED"
    emit({"ok": True, "task_id": task_id, "status": status, "model": model})


def handle_music_status(args, settings: dict) -> None:
    path = f"/suno/fetch/{urllib.parse.quote(args.task_id, safe='')}"
    if args.wait:
        result = poll(settings, path, normalize_music, args.timeout, args.interval)
    else:
        result = {"state": normalize_music(request_json(settings, "GET", path))}
    state = result["state"]

    files = []
    if state["status"] == "SUCCESS" and args.download:
        for index, url in enumerate(state["urls"]):
            raw = download(settings, url)
            path_saved = save_bytes("music", f"{slug(args.task_id, 24)}-{index + 1}", raw)
            files.append(str(path_saved))

    emit({"ok": True, "task_id": args.task_id, "status": state["status"], "progress": state["progress"],
          "urls": state["urls"], "reason": state["reason"], "files": files})


def normalize_audio_task(payload: dict) -> dict:
    data = payload.get("data")
    if not isinstance(data, dict):
        return {"status": "", "urls": [], "reason": ""}
    status = str(data.get("status") or "").upper()
    reason = data.get("error") or data.get("message") or ""
    return {"status": status, "urls": collect_audio_urls(data), "reason": str(reason)}


def audio_content_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".aac": "audio/aac",
        ".webm": "audio/webm",
        ".mp4": "video/mp4",
    }.get(ext, "application/octet-stream")


def handle_transcribe(args, settings: dict) -> None:
    model = args.model or pick_model(args, fetch_models(settings)["models"], "tts", "")

    if args.url:
        body = {"model": model, "input": {"audio_url": args.url}}
        if args.language:
            body["input"]["language_code"] = args.language
        payload = request_json(settings, "POST", "/v1/tasks", body=body)
        task_id = submit_task_id(payload)
        if not task_id:
            raise GatewayError(f"missing task id in response: {json.dumps(payload, ensure_ascii=False)[:300]}")
        saved = save_task({"task_id": task_id, "kind": "audio", "model": model,
                           "base_url": settings["base_url"],
                           "created_at": datetime.now().isoformat(timespec="seconds")})
        result = poll(settings, f"/v1/tasks/{urllib.parse.quote(task_id, safe='')}", normalize_transcript, 600, 5)
        state = result["state"]
        if state["status"] != "COMPLETED":
            raise GatewayError(f"task {task_id} ended with status {state['status']}: {state['reason']}")
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(result["payload"], ensure_ascii=False, indent=2), "utf-8")
        emit({"ok": True, "model": model, "task_id": task_id, "text": state["text"],
              "task_record": str(saved)})
        return

    if not args.file:
        raise GatewayError("--file is required for synchronous models; use --url for task-based transcription")

    source = Path(args.file)
    try:
        payload = source.read_bytes()
    except OSError as err:
        raise GatewayError(f"cannot read audio {args.file}: {err.strerror or err}") from None

    fields = [("model", model)]
    if args.language:
        fields.append(("language", args.language))
    if args.format:
        fields.append(("response_format", args.format))
    if args.group:
        fields.append(("group", args.group))
    files = [("file", source.name, payload, audio_content_type(source.name))]
    _, _, raw = request(settings, "POST", "/v1/audio/transcriptions", fields=fields, files=files)
    result = json.loads(raw.decode("utf-8", "replace"))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    emit({"ok": True, "model": model, "text": result.get("text", ""), "response": result})


def normalize_transcript(payload: dict) -> dict:
    data = payload.get("data")
    if not isinstance(data, dict):
        return {"status": "", "text": "", "reason": ""}
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    text = data.get("text") or output.get("text") or ""
    reason = data.get("error") or data.get("message") or ""
    return {"status": str(data.get("status") or "").upper(), "text": str(text), "reason": str(reason)}


def handle_balance(args, settings: dict) -> None:
    subscription = request_json(settings, "GET", "/v1/dashboard/billing/subscription")
    usage = request_json(settings, "GET", "/v1/dashboard/billing/usage")

    total = subscription.get("hard_limit_usd")
    used = usage.get("total_usage")
    remaining = None
    if isinstance(total, (int, float)) and isinstance(used, (int, float)) and total < 1e8:
        remaining = round(total - used, 4)

    emit({
        "ok": True,
        "base_url": settings["base_url"],
        "remaining": remaining,
        "used": used,
        "total": total,
        "unlimited": remaining is None,
        "unit": "site display unit as reported by /v1/dashboard/billing",
        "subscription": subscription,
        "usage": usage,
    })


def handle_tts_speak(args, settings: dict) -> None:
    model = pick_model(args, fetch_models(settings)["models"], "tts", "minimax-tts")
    transport = audio_transport(model)

    if transport == "chat":
        urls, inline = request_chat_audio(settings, model, args.input, voice=args.voice, group=args.group)
        files, urls = save_chat_audio("audio", slug(args.input), urls, inline, settings)
        emit({"ok": True, "model": model, "files": files, "urls": urls})
        return

    if transport == "task":
        voice = args.voice
        if "elevenlabs" in model.lower() and not voice:
            voice = DEFAULT_ELEVENLABS_VOICE
        if "text-to-dialogue" in model.lower():
            task_input = {"dialogue": [{"text": args.input, "voice": voice or DEFAULT_ELEVENLABS_VOICE}]}
        else:
            task_input = {"text": args.input}
            if voice:
                task_input["voice"] = voice
        body = {"model": model, "input": task_input}
        payload = request_json(settings, "POST", "/v1/tasks", body=body)
        task_id = submit_task_id(payload)
        if not task_id:
            raise GatewayError(f"missing task id in response: {json.dumps(payload, ensure_ascii=False)[:300]}")
        save_task({"task_id": task_id, "kind": "audio", "model": model, "base_url": settings["base_url"],
                   "created_at": datetime.now().isoformat(timespec="seconds")})
        result = poll(settings, f"/v1/tasks/{urllib.parse.quote(task_id, safe='')}", normalize_audio_task, 300, 5)
        state = result["state"]
        if state["status"] != "COMPLETED" or not state["urls"]:
            raise GatewayError(f"task {task_id} ended with status {state['status']}: {state['reason']}")
        files = [str(save_bytes("audio", f"{slug(args.input)}-{index + 1}", download(settings, url)))
                 for index, url in enumerate(state["urls"])]
        emit({"ok": True, "model": model, "task_id": task_id, "files": files, "urls": state["urls"]})
        return

    body = {"model": model, "input": args.input}
    if args.voice:
        body["voice"] = args.voice
    if args.format:
        body["response_format"] = args.format
    if args.speed is not None:
        body["speed"] = args.speed
    if args.instructions:
        body["instructions"] = args.instructions
    if args.group:
        body["group"] = args.group
    _, headers, raw = request(settings, "POST", "/v1/audio/speech", body=body)
    content_type = headers.get("Content-Type", "")
    looks_like_json = raw.lstrip()[:1] in (b"{", b"[")

    if "application/json" in content_type or looks_like_json:
        payload = json.loads(raw.decode("utf-8", "replace"))
        urls = collect_audio_urls(payload)
        if not urls:
            raise GatewayError(f"response contained no audio data: {json.dumps(payload, ensure_ascii=False)[:300]}")
        files = [str(save_bytes("audio", f"{slug(args.input)}-{index + 1}", download(settings, url)))
                 for index, url in enumerate(urls)]
        emit({"ok": True, "model": model, "files": files, "urls": urls})
        return

    path = save_bytes("audio", slug(args.input), raw, args.format or "")
    emit({"ok": True, "model": model, "files": [str(path)], "content_type": content_type})


def handle_tts_clone(args, settings: dict) -> None:
    if not args.name:
        raise GatewayError("--name is required")
    if not args.audio_url and not args.video_id:
        raise GatewayError("--audio-url or --video-id is required")
    body = {"model": "kling-custom-voices", "voice_name": args.name}
    if args.audio_url:
        body["voice_url"] = args.audio_url
    if args.video_id:
        body["video_id"] = args.video_id
    payload = request_json(settings, "POST", "/kling/v1/general/custom-voices", body=body)
    emit({"ok": True, "response": payload})


def handle_tts_clone_status(args, settings: dict) -> None:
    task_id = urllib.parse.quote(args.task_id, safe="")
    payload = request_json(settings, "GET", f"/kling/v1/general/custom-voices/{task_id}")
    emit({"ok": True, "response": payload})


def load_presets() -> dict:
    presets = _read_json(CORE_DIR / "presets.json").get("presets")
    return presets if isinstance(presets, dict) else {}


def read_state_argument(value: str):
    if not value:
        raise GatewayError("--state is required")
    if value.strip() == "-":
        return sys.stdin.read().strip()
    if value.strip().startswith("@") or Path(value).is_file():
        return load_json_argument(value)
    return load_json_argument(value)


def _fold(text: str) -> str:
    return re.sub(r"[\W_]+", " ", str(text).lower()).strip()


def check_questions(questions) -> dict:
    if not isinstance(questions, dict) or not questions:
        raise GatewayError("questions must be a non-empty object of {id: question}")
    cleaned = {}
    for raw_name, raw in questions.items():
        qid = str(raw_name)
        if not isinstance(raw, dict):
            raise GatewayError(f'question "{qid}" must be an object with type and instructions')
        kind = raw.get("type")
        if kind not in QUESTION_TYPES:
            raise GatewayError(f'question "{qid}" needs type in {list(QUESTION_TYPES)}')
        instructions = raw.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise GatewayError(f'question "{qid}" needs non-empty instructions')
        if _fold(instructions) == _fold(qid):
            raise GatewayError(f'question "{qid}" asks nothing: instructions only repeat the id')

        criteria = raw.get("criteria")
        if kind == "box":
            if criteria is not None:
                raise GatewayError(f'question "{qid}" is a box and takes no criteria')
            cleaned[qid] = {"type": "box", "instructions": instructions}
            continue
        if kind == "noul":
            question = {"type": "noul", "instructions": instructions}
            if criteria is not None:
                if not isinstance(criteria, dict) or not criteria or not set(map(str, criteria)) <= {"true", "false"}:
                    raise GatewayError(f'question "{qid}" noul criteria must be {{"true": "...", "false": "..."}}')
                question["criteria"] = {str(k): str(v) for k, v in criteria.items()}
            cleaned[qid] = question
            continue
        if kind == "choice":
            if not isinstance(criteria, dict) or not 2 <= len(criteria) <= MAX_CHOICE_OPTIONS:
                raise GatewayError(f'question "{qid}" choice needs 2 to {MAX_CHOICE_OPTIONS} options')
            cleaned[qid] = {"type": "choice", "instructions": instructions,
                            "criteria": {str(k): str(v) for k, v in criteria.items()}}
            continue
        if not isinstance(criteria, list) or not 2 <= len(criteria) <= MAX_SCORE_LEVELS:
            raise GatewayError(f'question "{qid}" score needs 2 to {MAX_SCORE_LEVELS} ordered levels')
        cleaned[qid] = {"type": "score", "instructions": instructions, "criteria": list(criteria)}
    return cleaned


def _unit(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionInvalid(f"{name} is not numeric")
    number = float(value)
    if not math.isfinite(number) or not -1e-6 <= number <= 1 + 1e-6:
        raise DecisionInvalid(f"{name} is outside 0..1")
    return min(1.0, max(0.0, number))


def _distribution(name: str, raw, options) -> dict:
    if not isinstance(raw, dict):
        raise DecisionInvalid(f"{name} probabilities are not an object")
    expected = set(map(str, options))
    found = set(map(str, raw))
    if found != expected:
        raise DecisionInvalid(f"{name} probabilities do not match the options offered")
    values = {str(key): _unit(raw[key], f"{name}.{key}") for key in raw}
    if abs(sum(values.values()) - 1.0) > 1e-3:
        raise DecisionInvalid(f"{name} probabilities do not sum to 1")
    return values


def read_answers(payload: dict, questions: dict) -> dict:
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise DecisionInvalid("response carries no answers")
    out = {}
    for qid, question in questions.items():
        answer = answers.get(qid)
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise DecisionInvalid(f'answer "{qid}" is missing or has the wrong type')
        kind = question["type"]
        if kind == "noul":
            probability = _unit(answer.get("noul"), qid)
            out[qid] = {"type": "noul", "value": probability >= 0.5, "probability": probability}
            continue
        if kind == "choice":
            options = list(question["criteria"])
            picked = answer.get("choice")
            if picked not in options:
                raise DecisionInvalid(f'answer "{qid}" chose an option that was not offered')
            probabilities = _distribution(qid, answer.get("probabilities"), options)
            if probabilities[picked] < max(probabilities.values()) - ARGMAX_TOLERANCE:
                raise DecisionInvalid(f'answer "{qid}" is not the most likely option')
            out[qid] = {"type": "choice", "value": picked,
                        "probability": probabilities[picked], "probabilities": probabilities}
            continue
        value = answer.get("score")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DecisionInvalid(f'answer "{qid}" has no numeric score')
        levels = len(question["criteria"])
        if not -0.5 <= float(value) <= levels - 0.5:
            raise DecisionInvalid(f'answer "{qid}" scored outside the rubric')
        level = int(round(float(value)))
        raw_spread = answer.get("probabilities")
        spread = {}
        if isinstance(raw_spread, dict) and raw_spread:
            spread = {int(k): _unit(v, f"{qid}.{k}") for k, v in
                      _distribution(qid, raw_spread, [str(i) for i in range(levels)]).items()}
        out[qid] = {"type": "score", "value": level, "score": float(value),
                    "probability": spread.get(level, 1.0 / max(levels, 1)), "probabilities": spread}
    return out


def parse_thresholds(spec: str, preset_thresholds: dict) -> dict:
    thresholds = {str(k): float(v) for k, v in (preset_thresholds or {}).items()}
    if not spec:
        return thresholds
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise GatewayError("--decide expects id=threshold pairs, for example risk=0.7")
        key, raw_value = item.split("=", 1)
        try:
            thresholds[key.strip()] = float(raw_value)
        except ValueError:
            raise GatewayError(f"--decide value for {key.strip()} is not a number") from None
    return thresholds


def evaluate(answers: dict, thresholds: dict) -> dict:
    decisions = {}
    accepted = True
    for qid, answer in answers.items():
        threshold = thresholds.get(qid)
        if threshold is None:
            decisions[qid] = {**answer, "threshold": None, "accepted": None}
            continue
        passed = answer["probability"] >= threshold
        decisions[qid] = {**answer, "threshold": threshold, "accepted": passed}
        accepted = accepted and passed
    return {"decisions": decisions, "accepted": accepted}


def handle_decision(args, settings: dict) -> None:
    started = time.monotonic()
    state = read_state_argument(args.state)
    presets = load_presets()
    preset = presets.get(args.preset) if args.preset else {}

    bypass_marker = ""
    if isinstance(state, str):
        bypass_marker = state.lower()
    elif isinstance(state, dict):
        bypass_marker = " ".join(str(state.get(key, "")) for key in ("goal", "raw", "message", "user_message"))
    if args.off or "bypass jev" in bypass_marker or "no jev" in bypass_marker:
        emit({"ok": True, "mode": args.mode, "jev_used": False,
              "action": args.fallback or (preset or {}).get("fallback") or None,
              "reason": "kill switch", "decisions": {}})
        return

    if args.preset and preset is None:
        raise GatewayError(f"unknown preset '{args.preset}'; available: {', '.join(sorted(presets)) or 'none'}")
    preset = preset or {}

    questions = dict(preset.get("questions") or {})
    override = load_json_argument(args.questions) if args.questions else None
    if override:
        if not isinstance(override, dict):
            raise GatewayError("--questions must be an object of {id: question}")
        questions.update(override)
    questions = check_questions(questions)

    encoded_state = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
    if len(encoded_state) > MAX_STATE_CHARS:
        raise GatewayError(f"state is {len(encoded_state)} chars; the limit is {MAX_STATE_CHARS}")

    model = args.model
    if not model:
        matches = resolve_alias("jev", fetch_models(settings)["models"])
        if not matches:
            raise GatewayError("no decision model available; pass --model")
        model = matches[0]["id"]

    thresholds = parse_thresholds(args.decide, preset.get("thresholds") or {})

    try:
        payload = request_json(settings, "POST", "/v1/systemone",
                               body={"model": model, "state": state, "questions": questions})
        answers = read_answers(payload, questions)
    except GatewayError as err:
        if args.mode == "active" and not args.fallback:
            raise
        emit({"ok": True, "mode": args.mode, "jev_used": False, "fail_open": True,
              "action": args.fallback or preset.get("fallback") or None,
              "reason": f"{err.code or 'decision_failed'}: {err.message}",
              "decisions": {}, "latency_ms": int((time.monotonic() - started) * 1000)})
        return

    evaluated = evaluate(answers, thresholds)
    action = None
    for qid in preset.get("actions") or list(thresholds):
        if qid in evaluated["decisions"]:
            decision = evaluated["decisions"][qid]
            action = decision.get("value")
            break
    if not evaluated["accepted"] and args.fallback:
        action = args.fallback

    result = {
        "ok": True,
        "mode": args.mode,
        "jev_used": True,
        "model": model,
        "jev_model": payload.get("model"),
        "preset": args.preset or None,
        "action": action,
        "accepted": evaluated["accepted"],
        "decisions": evaluated["decisions"],
        "usage": payload.get("usage"),
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**result, "response": payload}, ensure_ascii=False, indent=2), "utf-8")
    emit(result)


def handle_task(args, settings: dict) -> None:
    record = load_task(args.task_id)
    kind = args.kind or record.get("kind")
    if not kind:
        raise GatewayError("task kind unknown; pass --kind video|music")
    if record.get("base_url"):
        settings = {**settings, "base_url": record["base_url"]}
    if kind == "video":
        handle_video_status(argparse.Namespace(task_id=args.task_id, wait=args.wait, timeout=args.timeout,
                                               interval=args.interval, download=args.download), settings)
        return
    handle_music_status(argparse.Namespace(task_id=args.task_id, wait=args.wait, timeout=args.timeout,
                                           interval=args.interval, download=args.download), settings)


def handle_doctor(args, settings: dict) -> None:
    report = {"ok": True, "base_url": settings["base_url"], "state_dir": str(STATE_DIR),
              "sources": settings["sources"], "api_key": mask_secret(settings["api_key"]),
              "api_key_configured": bool(settings["api_key"])}
    try:
        result = fetch_models(settings, refresh=True)
        report["models"] = {"source": result["source"], "count": len(result["models"])}
        report["ok"] = bool(result["models"])
    except GatewayError as err:
        report["ok"] = False
        report["error"] = {"message": err.message, "status": err.status}
    emit(report)


def load_json_argument(value: str):
    if not value:
        return None
    candidate_text = value[1:] if value.startswith("@") else value
    if len(candidate_text) < 4096:
        try:
            candidate = Path(candidate_text)
            if candidate.is_file():
                value = candidate.read_text("utf-8")
        except OSError:
            pass
    try:
        return json.loads(value)
    except ValueError:
        return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gateway.py",
        description=f"AI gateway skill core for {PLATFORM} ({PLATFORM_URL})",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            f"{PLATFORM} · {PLATFORM_URL}\n"
            f"{PLATFORM_DESC_ZH}\n"
            f"{PLATFORM_DESC_EN}\n"
            f"Repository: {REPO_URL}"
        ),
    )
    parser.add_argument("--request-timeout", dest="request_timeout", type=int, default=0,
                        help="override the single-request timeout in seconds")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="store an API key")
    login.add_argument("--key", required=True)
    login.add_argument("--base-url", default="")
    login.add_argument("--group", default="")
    login.add_argument("--skill", default="")

    config = sub.add_parser("config", help="show resolved settings")
    config.add_argument("--skill", default="")

    models = sub.add_parser("models", help="list available models")
    models.add_argument("--category", default="all",
                        choices=["all", "image", "video", "music", "tts", "embedding", "decision", "text"])
    models.add_argument("--refresh", action="store_true")
    models.add_argument("--skill", default="")

    resolve = sub.add_parser("resolve", help="map an alias to a model id")
    resolve.add_argument("alias")
    resolve.add_argument("--skill", default="")

    image = sub.add_parser("image", help="image generation and editing")
    image_sub = image.add_subparsers(dest="action", required=True)
    generate = image_sub.add_parser("generate")
    generate.add_argument("--prompt", required=True)
    generate.add_argument("--model", default="")
    generate.add_argument("--size", default="")
    generate.add_argument("--n", type=int, default=None)
    generate.add_argument("--quality", default="")
    generate.add_argument("--output-format", dest="output_format", default="")
    generate.add_argument("--background", default="")
    generate.add_argument("--moderation", default="")
    generate.add_argument("--complexity", default="")
    generate.add_argument("--output-compression", dest="output_compression", type=int, default=None)
    generate.add_argument("--frame-count", dest="frame_count", type=int, default=None)
    generate.add_argument("--frame-duration-ms", dest="frame_duration_ms", type=int, default=None)
    generate.add_argument("--group", default="")
    edit = image_sub.add_parser("edit")
    edit.add_argument("--prompt", required=True)
    edit.add_argument("--image", action="append", default=[])
    edit.add_argument("--mask", default="")
    edit.add_argument("--markup", default="")
    edit.add_argument("--model", default="")
    edit.add_argument("--size", default="")
    edit.add_argument("--n", type=int, default=None)
    edit.add_argument("--quality", default="")
    edit.add_argument("--output-format", dest="output_format", default="")
    edit.add_argument("--background", default="")
    edit.add_argument("--moderation", default="")
    edit.add_argument("--complexity", default="")
    edit.add_argument("--output-compression", dest="output_compression", type=int, default=None)
    edit.add_argument("--group", default="")

    video = sub.add_parser("video", help="video generation tasks")
    video_sub = video.add_subparsers(dest="action", required=True)
    create = video_sub.add_parser("create")
    create.add_argument("--prompt", default="")
    create.add_argument("--model", default="")
    create.add_argument("--duration", type=int, default=None)
    create.add_argument("--seconds", default="")
    create.add_argument("--size", default="")
    create.add_argument("--mode", default="")
    create.add_argument("--ratio", default="")
    create.add_argument("--width", type=int, default=None)
    create.add_argument("--height", type=int, default=None)
    create.add_argument("--image", action="append", default=[])
    create.add_argument("--images", action="append", default=[])
    create.add_argument("--reference-video", dest="reference_video", action="append", default=[])
    create.add_argument("--reference-audio", dest="reference_audio", action="append", default=[])
    create.add_argument("--audio", action="store_true")
    create.add_argument("--content", default="")
    create.add_argument("--metadata", default="")
    create.add_argument("--group", default="")
    status = video_sub.add_parser("status")
    status.add_argument("task_id")
    status.add_argument("--wait", action="store_true")
    status.add_argument("--timeout", type=int, default=900)
    status.add_argument("--interval", type=int, default=5)
    status.add_argument("--download", action="store_true")

    music = sub.add_parser("music", help="music generation tasks")
    music_sub = music.add_subparsers(dest="action", required=True)
    music_create = music_sub.add_parser("create")
    music_create.add_argument("--prompt", default="")
    music_create.add_argument("--model", default="")
    music_create.add_argument("--title", default="")
    music_create.add_argument("--tags", default="")
    music_create.add_argument("--make-instrumental", dest="make_instrumental", action="store_true")
    music_create.add_argument("--task-id", dest="task_id", default="")
    music_create.add_argument("--cover-clip", dest="cover_clip_id", default="")
    music_create.add_argument("--continue-clip", dest="continue_clip_id", default="")
    music_create.add_argument("--continue-at", dest="continue_at", type=float, default=None)
    music_create.add_argument("--upload-url", dest="upload_url", default="")
    music_create.add_argument("--group", default="")
    music_status = music_sub.add_parser("status")
    music_status.add_argument("task_id")
    music_status.add_argument("--wait", action="store_true")
    music_status.add_argument("--timeout", type=int, default=900)
    music_status.add_argument("--interval", type=int, default=5)
    music_status.add_argument("--download", action="store_true")

    tts = sub.add_parser("tts", help="speech synthesis and voice cloning")
    tts_sub = tts.add_subparsers(dest="action", required=True)
    speak = tts_sub.add_parser("speak")
    speak.add_argument("--input", required=True)
    speak.add_argument("--model", default="")
    speak.add_argument("--voice", default="")
    speak.add_argument("--format", default="")
    speak.add_argument("--speed", type=float, default=None)
    speak.add_argument("--instructions", default="")
    speak.add_argument("--group", default="")
    clone = tts_sub.add_parser("clone")
    clone.add_argument("--name", required=True)
    clone.add_argument("--audio-url", dest="audio_url", default="")
    clone.add_argument("--video-id", dest="video_id", default="")
    clone_status = tts_sub.add_parser("clone-status")
    clone_status.add_argument("task_id")

    transcribe = sub.add_parser("transcribe", help="speech to text")
    transcribe.add_argument("--file", default="", help="local audio or video file for synchronous models")
    transcribe.add_argument("--url", default="", help="public audio URL for task-based models")
    transcribe.add_argument("--model", default="")
    transcribe.add_argument("--language", default="")
    transcribe.add_argument("--format", default="")
    transcribe.add_argument("--group", default="")
    transcribe.add_argument("--out", default="")
    transcribe.add_argument("--skill", default="")

    balance = sub.add_parser("balance", help="show quota and usage")
    balance.add_argument("--skill", default="")

    decision = sub.add_parser("decision", help="typed decisions with calibrated confidence")
    decision.add_argument("--state", required=True, help="inline JSON, @file, plain text, or - for stdin")
    decision.add_argument("--preset", default="", help="named question set from core/presets.json")
    decision.add_argument("--questions", default="", help="inline JSON or @file, merged over the preset")
    decision.add_argument("--decide", default="", help="id=threshold pairs, comma separated")
    decision.add_argument("--fallback", default="", help="action to use when confidence is low or the call fails")
    decision.add_argument("--mode", default="shadow", choices=["shadow", "active"])
    decision.add_argument("--off", action="store_true", help="kill switch, skip the call")
    decision.add_argument("--model", default="")
    decision.add_argument("--out", default="")

    task = sub.add_parser("task", help="query a stored task")
    task.add_argument("task_id")
    task.add_argument("--kind", default="")
    task.add_argument("--wait", action="store_true")
    task.add_argument("--timeout", type=int, default=900)
    task.add_argument("--interval", type=int, default=5)
    task.add_argument("--download", action="store_true")

    doctor = sub.add_parser("doctor", help="verify credentials and connectivity")
    doctor.add_argument("--skill", default="")
    return parser


DISPATCH = {
    ("login", None): handle_login,
    ("config", None): handle_config,
    ("models", None): handle_models,
    ("resolve", None): handle_resolve,
    ("image", "generate"): handle_image_generate,
    ("image", "edit"): handle_image_edit,
    ("video", "create"): handle_video_create,
    ("video", "status"): handle_video_status,
    ("music", "create"): handle_music_create,
    ("music", "status"): handle_music_status,
    ("tts", "speak"): handle_tts_speak,
    ("tts", "clone"): handle_tts_clone,
    ("tts", "clone-status"): handle_tts_clone_status,
    ("transcribe", None): handle_transcribe,
    ("balance", None): handle_balance,
    ("decision", None): handle_decision,
    ("task", None): handle_task,
    ("doctor", None): handle_doctor,
}


def main(argv: list | None = None) -> None:
    args = build_parser().parse_args(argv)
    skill = getattr(args, "skill", "") or SKILL_BY_COMMAND.get(args.command, "")
    settings = resolve_settings(skill or None)
    if getattr(args, "request_timeout", 0) > 0:
        settings["timeout"] = args.request_timeout
    handler = DISPATCH[(args.command, getattr(args, "action", None))]

    try:
        handler(args, settings)
    except GatewayError as err:
        fail(err.code or "request_failed", err.message, err.status)
    except KeyboardInterrupt:
        fail("interrupted", "cancelled by user")
    except Exception as err:
        fail("internal_error", f"{type(err).__name__}: {err}")


if __name__ == "__main__":
    main()

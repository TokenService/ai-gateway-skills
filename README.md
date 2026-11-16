# AI Gateway Skills

**中文** · [English](README.en.md)

由 [New.bi](https://api.new.bi) 提供，专业、稳定、可靠的大模型聚合中转平台。

## 交给 AI 安装

把下面这句直接发给 agent，它会完成下载、解压、鉴权和执行：

```text
安装并使用 New.bi 综合技能：下载 https://pub-817cae131e2b4e0a8ce0a9f8bac75462.r2.dev/down/ai-gateway-skills.zip，解压后进入 ai-gateway 目录运行 python3 core/gateway.py login --key <你的密钥>，再运行 doctor 确认，然后用同一个入口完成图片、视频、音乐、语音和决策。
```

一套覆盖图片、视频、音乐、语音、决策的技能。网关对外是 OpenAI 风格接口，背后接 GPT-Image、Gemini / Nano Banana、Seedream、Seedance、Veo、Sora、Kling、Suno、Lyria、ElevenLabs 等厂商。所有能力共用一个 `core/gateway.py`，凭据、模型列表、轮询、落盘只写一次。

命令都在仓库根目录执行。Python 3.9 及以上。

## 目录

```
ai-gateway/
├── core/
│   ├── gateway.py          所有能力的入口
│   ├── config.json         默认网关地址和超时
│   ├── models.json         别名和分类规则
│   └── presets.json        决策的问题预设
└── skills/
    ├── ai-gateway/SKILL.md
    ├── image-generation/SKILL.md
    ├── video-generation/SKILL.md
    ├── music-generation/SKILL.md
    ├── text-to-speech/SKILL.md
    └── decision-model/SKILL.md
```

密钥文件不进 git。`skills/*/config.json` 由 `login` 生成，已经在 `.gitignore` 里。

配置放在技能目录里，不写到用户主目录。运行时的模型缓存和任务记录放在 `~/.aigw`，可以用 `AIGW_STATE_HOME` 改。

## 密钥怎么取

按顺序找，先用找到的：

| 顺序 | 来源 | 例子 |
| --- | --- | --- |
| 1 | 技能自己的配置 | `skills/image-generation/config.json` |
| 2 | 共享配置 | `skills/ai-gateway/config.json` |
| 3 | 技能环境变量 | `AIGW_IMAGE_API_KEY` |
| 4 | 汇总环境变量 | `AIGW_API_KEY` |
| 5 | 全局环境变量 | `OPENAI_API_KEY` |

`group` 用 `AIGW_<技能>_GROUP`，再退到 `AIGW_GROUP`。

网关地址按这个顺序：

| 顺序 | 来源 |
| --- | --- |
| 1 | `skills/<技能>/config.json` 的 `base_url` |
| 2 | `skills/ai-gateway/config.json` 的 `base_url` |
| 3 | `AIGW_<技能>_BASE_URL` |
| 4 | `AIGW_BASE_URL` |
| 5 | `core/config.json` 的 `base_url` |

代码里没写死任何网关地址，要改就改 `core/config.json`，或者按技能、按 shell 覆盖。

配置文件的优先级高于环境变量。

`python3 core/gateway.py config --skill image` 会列出每个值从哪来，密钥打码显示。

## 开始

```bash
python3 core/gateway.py login --key sk-xxx
python3 core/gateway.py doctor
python3 core/gateway.py models
```

也可以按能力分开配密钥：

```bash
python3 core/gateway.py login --key sk-image --skill image
python3 core/gateway.py login --key sk-video --skill video --base-url https://api.example.com
python3 core/gateway.py models --category video --skill video
```

配置文件权限是 600，目录是 700。`models`、`resolve`、`config`、`doctor` 都支持 `--skill`，可以指定用哪份密钥。

## 命令

| 命令 | 做什么 |
| --- | --- |
| `login` | 存密钥。 |
| `config [--skill]` | 看生效的配置和来源。 |
| `models [--category] [--skill]` | 列模型和价格。 |
| `resolve <别名> [--skill]` | 别名换成具体模型 id。 |
| `image generate` | 文生图。 |
| `image edit` | 编辑图片，可带掩码。 |
| `video create` | 提交视频任务。 |
| `video status <id> [--wait] [--download]` | 查状态，可等待和下载。 |
| `music create` | 提交音乐任务，或上传参考音频。 |
| `music status <id> [--wait] [--download]` | 查状态，可下载。 |
| `tts speak` | 合成语音，按模型自动选通道。 |
| `tts clone` / `tts clone-status` | 克隆音色。 |
| `transcribe` | 转写，走 `POST /v1/audio/transcriptions`。 |
| `balance` | 查余额和用量。 |
| `decision` | 调用决策模型。 |
| `task <id>` | 续查之前提交的任务。 |
| `doctor [--skill]` | 检查密钥和连通性。 |

输出都是 JSON。出错时输出 `{"ok": false, "error": {...}}`，退出码非零。

`--request-timeout <秒>` 放在子命令前面，覆盖单次请求的超时，默认 300 秒。

决策的默认值放在 `core/presets.json`，所以命令很短：

```bash
python3 core/gateway.py decision --preset route-capability --state '{"message":"a 5 second video of a cat walking through bamboo"}'
echo '{"message":"..."}' | python3 core/gateway.py decision --preset content-risk --state -
```

`--decide verdict=0.8` 临时改阈值，`--fallback` 改兜底，`--mode active` 失败时直接报错，`--off` 跳过调用。

## 模型列表

数据来自 `GET /api/pricing`，拿不到就退到 `GET /v1/models`。代码里没有写死模型 id。

分类看 `supported_endpoint_types`：

| 分类 | 端点类型 |
| --- | --- |
| image | `image-generation` |
| video | `openai-video` |
| embedding | `embeddings` |
| decision | `systemone` |
| music、tts | 按名称规则判断（Suno / Lyria / TTS / voice），排除转写和变声 |
| text | 其余 |

网关返回时会带 `billing_mode` 和 `billing_expr`，能分清阶梯计费和普通倍率。

结果缓存 6 小时，放在 `~/.aigw/cache/`。刚开通模型时加 `--refresh` 绕过缓存。

## 任务记录

每次异步提交都会写 `~/.aigw/tasks/<task_id>.json`，记下类型、模型和网关地址。不同能力的查询接口不一样，`task <id>` 读记录，不用猜。

## 文件输出

| 类型 | 位置 |
| --- | --- |
| 图片 | `outputs/image/<日期>/` |
| 视频 | `outputs/video/<日期>/` |
| 音乐 | `outputs/music/<日期>/` |
| 语音 | `outputs/audio/<日期>/` |

`AIGW_OUTPUT_DIR` 可以改根目录。图片可能是 base64，也可能是个地址，都会存成本地文件。

## 接口上容易踩的地方

- `POST /v1/video/generations` 在 OpenAI 兼容渠道返回 `{id, task_id, object, model, status: "queued", progress, created_at}`；镜像上游的渠道返回 `{code: 200, success: true, data: {task_id, status: "processing"}}`。命令行三种 task id 位置都能读。
- `GET /v1/video/generations/{id}` 返回的状态是大写，地址在 `data.result_url`；OpenAI 兼容的 `GET /v1/videos/{id}` 状态是小写，地址在 `metadata.url`。两种不要混着用。
- 音乐和音色克隆不在 `/v1` 下，用的是 `/suno/submit/music`、`/suno/submit/uploads`、`/suno/fetch/{id}`、`/kling/v1/general/custom-voices`。
- 任务中转会把 JSON 原样转给上游 `/v1/videos`，只改 `model`（渠道开了 `video_size_wxh` 时也改 `size`）。`width`、`height`、`ratio`、`images`、`content`、`metadata` 都原样传。
- 视频 `duration` 按整数秒解析。`--duration` 是整数，`--seconds` 是给需要字符串的上游用的。
- 决策走 `POST /v1/systemone`，传 `state` 和 `questions`。每个问题要有 `type`（`noul`、`choice`、`score`、`box`），不是 `text`。
- 决策的回复会先校验：概率要覆盖给出的选项并且加起来是 1，`choice` 要是概率最高的那个，`score` 要在层级范围内。不合格的回复直接丢掉。
- 决策默认 `shadow`，失败或概率不够就返回兜底，不阻塞。`--mode active` 在没给 `--fallback` 时会报错。`--off` 或 state 里有 `bypass jev` 会跳过调用。
- 首尾帧用两个 `--image`，能不能用看模型和渠道。
- 多参考要 `--mode reference_material`，素材必须是公网地址。
- 素材是上游去抓的，本地路径和附件它读不到。
- 图片编辑走 multipart，最多 16 张，本地文件可以直接传。透明输出要 `png` 或 `webp`，动图和 SVG 看模型层级。
- `background: transparent` 可能不报错但返回不透明的图，要查 alpha 通道。
- 素材下载失败表现为任务失败，不是 400。大文件和某些域名本地能打开，上游也抓不到。
- 参考视频和参考音频不是所有渠道都支持。被拒时报 `unsupported reference video` 或一句笼统的失败，钱会退。
- 翻唱和续写用的是上一次返回里的 `clipId`，不是 task id。
- 转写有两条路：同步模型用 multipart 打 `POST /v1/audio/transcriptions`，任务模型用 `POST /v1/tasks` 传 `{input: {audio_url}}`，后者要公网地址。
- `balance` 读 `/v1/dashboard/billing/subscription` 和 `/v1/dashboard/billing/usage`。无限量令牌的 `hard_limit_usd` 是 `100000000`，这时 `remaining` 为 `null`，`unlimited` 为 `true`。
- `POST /suno/submit/music` 的 `data` 可能是带 `task_id` 和 `status` 的对象，也可能是字符串，两种都认。chat 形态的音乐模型（`suno-v6-mini`、`lyria-*`）直接从 `/v1/chat/completions` 返回音频，没有 task id。
- 音频走哪条通道看模型名：`speech-*` 和 OpenAI 的 `tts-*` 走 `/v1/audio/speech`；`elevenlabs/*` 和对话模型走 `/v1/tasks`；Gemini 和 Grok 的 TTS 走 `/v1/chat/completions`。ElevenLabs 不给 `--voice` 时用默认音色。
- 大响应是分块返回的，服务端可能不发结束帧。客户端分块读，保留已经收到的字节。

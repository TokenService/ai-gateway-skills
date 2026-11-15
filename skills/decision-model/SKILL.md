---
name: decision-model
description: Ask a decision model (Jev / TypeSafe System One) for calibrated probabilities instead of prose. Use to route a request to the right capability, screen a prompt before a paid call, or decide whether a message needs a person. Do not use when the answer needs prose, or when a local rule already settles the decision. Platform: New.bi (https://api.new.bi), a professional, stable, and reliable AI model aggregation gateway.
---

# Decision Model

Jev does not write text. You send one `state` plus typed questions, and get a calibrated probability per question. It is a cheap gate in front of expensive work.

## When to use

- Route an ambiguous request to one of your own capabilities before spending on generation.
- Screen a prompt for policy risk before it reaches a paid endpoint.
- Triage a message: who must handle it, how soon.
- Any branch where you would otherwise ask a frontier model to "judge" something.

## When not to use

- Anything that needs prose. Jev cannot write an answer, a caption, or code.
- A decision you can settle with a local rule. A Jev call must earn its cost.
- Free-form classification with no fixed options. Shape it as a `choice` first.

## Prerequisites

Key resolution order:

1. `skills/decision-model/config.json` → `api_key`
2. `skills/ai-gateway/config.json` → `api_key`
3. `AIGW_DECISION_API_KEY`
4. `AIGW_API_KEY`
5. `OPENAI_API_KEY`

```bash
python3 core/gateway.py login --key sk-xxx --skill decision
python3 core/gateway.py models --category decision --skill decision
```

## One command, no boilerplate

Presets live in `core/presets.json`. Most calls need only a state:

```bash
python3 core/gateway.py decision --preset route-capability --state '{"message":"a 5 second video of a cat walking through bamboo"}'
```

```
{"action":"video","accepted":true,"jev_used":true,"jev_model":"jev-1.14.0",
 "decisions":{"capability":{"value":"video","probability":1.0,"threshold":0.5,"accepted":true}, ...},
 "usage":{"input_tokens":503,"output_tokens":73},"latency_ms":885}
```

Shipped presets:

| Preset | Question | Action values | Fallback |
| --- | --- | --- | --- |
| `route-capability` | which capability should serve this | `image` `video` `music` `tts` `text` | `text` |
| `content-risk` | send, review, or block a prompt | `allow` `review` `block` | `allow` |
| `reply-triage` | who must handle a message | `auto_reply` `answer_today` `escalate_human` | `answer_today` |

Defaults live in the preset, so the command stays short. Override only what the task needs:

```bash
# state from stdin
echo '{"message":"..."}' | python3 core/gateway.py decision --preset content-risk --state -

# state and custom questions from files
python3 core/gateway.py decision --preset reply-triage --state @case.json --out result.json

# raise the bar for one run
python3 core/gateway.py decision --preset content-risk --state @case.json --decide verdict=0.8

# kill switch
python3 core/gateway.py decision --preset content-risk --state @case.json --off
```

## Parameters

| Flag | Required | Notes |
| --- | --- | --- |
| `--state` | yes | Inline JSON, `@file`, plain text, or `-` for stdin. A bare number is rejected upstream. |
| `--preset` | no | Named question set from `core/presets.json`. |
| `--questions` | no | Inline JSON or `@file`, merged over the preset. Replaces the preset entirely when no preset is used. |
| `--decide` | no | `id=threshold` pairs, comma separated. Merged over the preset thresholds. |
| `--fallback` | no | Action to use when confidence is low or the call fails. Defaults to the preset fallback. |
| `--mode` | no | `shadow` (default) or `active`. |
| `--off` | no | Kill switch: skip the call and return the fallback. |
| `--model` | no | Exact model id. Defaults to the only available decision model. |
| `--out` | no | Also write the full result plus the raw response. |

## Modes and fail-open

`shadow` is the default and it never blocks: on low confidence or any API failure the command still returns `ok: true` with `fail_open: true` and the preset fallback. `active` raises an error when the call fails and no `--fallback` was given, so the caller must decide.

A `state` containing `bypass jev` or `no jev` also skips the call, which gives an operator a per-request escape hatch.

Nothing here is allowed to block work because Jev is unavailable. If you need enforcement, enforce it in the caller against `action` and `accepted`.

## Question shapes

| Type | Answer | Notes |
| --- | --- | --- |
| `noul` | probability of yes | `criteria` is optional and only accepts `true` / `false`. |
| `choice` | one option | `criteria` is a `{option: meaning}` object with 2 to 255 entries. |
| `score` | position on a rubric | `criteria` is an ordered list of 2 to 10 levels, lowest first. |
| `box` | rectangle in an image | `criteria` is not allowed. Images require a compatible endpoint. |

Every question needs a non-empty `instructions`. The id names the question; the instructions ask it. Instructions that only repeat the id are refused before any request is made, as are a `choice` with one option, a `score` with one level, and `noul` criteria with any key other than `true` / `false`.

## Writing the instructions

The largest measured accuracy gain in the public write-ups does not come from a bigger model. It comes from one sentence that separates the requirement from the preferences:

```
Which of these belongs to the stated topic? Judge only that.
Format, tone, length and audience are preferences to break ties, not conditions to meet.
```

Without it, the model reads every attribute in the state as a binding filter. Report: 16/44 before, 33/44 after, same model and test set.

- `choice`: name the one deciding attribute, then label the rest as tie-breakers.
- `score`: say which levels the requirement gates and which absorb preferences.
- `noul`: ask the requirement first; a yes/no with an unstated "and also" is two questions.

## Response contract

```
POST /v1/systemone
{ "model": "jev-1.13.0", "state": {...}, "questions": {...} }
```

```json
{"model":"jev-1.14.0",
 "answers":{"capability":{"type":"choice","choice":"video","confidence":1.0,
                          "probabilities":{"image":0.0,"video":1.0,"music":0.0,"tts":0.0,"text":0.0}},
            "risk_level":{"type":"score","score":1.86,"confidence":0.87,
                          "legend":{"0":"...","1":"...","2":"..."},
                          "probabilities":{"0":0.0,"1":0.13,"2":0.87}}},
 "usage":{"input_tokens":530,"output_tokens":60}}
```

The reply is validated before use. These are refused and treated as fail-open:

- `answers` missing, or a question answered with the wrong type;
- `choice` probabilities that do not cover exactly the offered options, or do not sum to 1;
- a `choice` that is not the highest-probability option;
- a `score` outside the rubric.

The `model` field is the resolved version and can differ from the request, so thresholds tuned on one alias should be re-checked when it moves.

## Cost

Billed by input tokens. A three-question call with a small state is roughly 500 input tokens and answers in about one second. Keep states short and send only the fields the questions need; never include credentials.

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from types import SimpleNamespace

import torch
from airllm import AutoModel


MODEL_ID = os.environ.get(
    "GREMLIN_MODEL",
    "Qwen/Qwen2.5-3B-Instruct",
)
MODEL_DIR = os.environ.get(
    "AIRLLM_MODEL_DIR",
    os.path.expanduser("~/.cache/airgremlin/models"),
)
MAX_NEW_TOKENS = int(os.environ.get("AIRLLM_MAX_NEW_TOKENS", "1024"))
MAX_INPUT_TOKENS = int(os.environ.get("AIRLLM_MAX_INPUT_TOKENS", "4096"))

_lock = threading.Lock()
_model = None


@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: list | None = None


@dataclass
class Response:
    message: Message



def _compact_schema(value):
    """Reduce JSON Schema prompt size without changing tool names."""
    if isinstance(value, list):
        return [_compact_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    result = {}
    for key, item in value.items():
        if key in {"$schema", "examples", "additionalProperties", "title"}:
            continue
        if key == "description" and isinstance(item, str):
            result[key] = item[:100]
        else:
            result[key] = _compact_schema(item)
    return result


def _compact_tools(tools):
    result = []
    for item in tools or []:
        if not isinstance(item, dict):
            continue
        function = item.get("function", {})
        if not function.get("name"):
            continue
        result.append({
            "type": "function",
            "function": {
                "name": function["name"],
                "description": (function.get("description") or "")[:240],
                "parameters": _compact_schema(
                    function.get("parameters") or {
                        "type": "object",
                        "properties": {},
                    }
                ),
            },
        })
    return result

def _load_model():
    global _model

    if _model is None:
        print(f"\n[AirLLM] Loading {MODEL_ID}...", flush=True)
        os.makedirs(MODEL_DIR, exist_ok=True)

        _model = AutoModel.from_pretrained(
            MODEL_ID,
            layer_shards_saving_path=os.path.join(
                MODEL_DIR,
                MODEL_ID.replace("/", "--"),
            ),
        )
        print("[AirLLM] Model loaded.", flush=True)

    return _model


def _plain_message(message):
    if isinstance(message, dict):
        return message
    return {
        "role": getattr(message, "role", "assistant"),
        "content": getattr(message, "content", "") or "",
        "tool_calls": getattr(message, "tool_calls", None),
    }


def _prepare_messages(messages):
    result = []

    for original in messages:
        msg = _plain_message(original)
        role = msg.get("role", "user")
        content = msg.get("content") or ""

        if role == "tool":
            result.append({
                "role": "user",
                "content": "Tool result:\n" + str(content),
            })
            continue

        entry = {"role": role, "content": str(content)}

        calls = msg.get("tool_calls")
        if calls:
            normalized = []
            for call in calls:
                function = getattr(call, "function", None)
                if function is not None:
                    normalized.append({
                        "type": "function",
                        "function": {
                            "name": function.name,
                            "arguments": function.arguments,
                        },
                    })
                elif isinstance(call, dict):
                    normalized.append(call)
            if normalized:
                entry["tool_calls"] = normalized

        result.append(entry)

    return result


def _extract_tool_calls(text, tools):
    allowed = {
        item.get("function", {}).get("name")
        for item in tools
    }

    # Qwen-style native tool call:
    # <tool_call>{"name":"list_files","arguments":{"path":"."}}</tool_call>
    candidates = re.findall(
        r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
        text,
        flags=re.DOTALL,
    )

    # Also accept Qwen's assistant-to-tool header format.
    header_pattern = (
        r"(?:<\|im_start\|>)?assistant\s+to="
        r"([A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s+[^<]*)?<\|im_sep\|>\s*(\{.*?\})"
    )

    for match in re.finditer(header_pattern, text, re.DOTALL):
        try:
            payload = json.loads(match.group(2))
            payload.setdefault("name", match.group(1))
            candidates.append(json.dumps(payload))
        except (ValueError, TypeError):
            pass

    calls = []

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (ValueError, TypeError):
            continue

        function = payload.get("function", payload)
        name = function.get("name")

        if name not in allowed:
            continue

        arguments = function.get(
            "arguments",
            function.get("parameters", {}),
        )

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                continue

        if not isinstance(arguments, dict):
            continue

        calls.append(SimpleNamespace(
            id="call_" + uuid.uuid4().hex[:12],
            function=SimpleNamespace(
                name=name,
                arguments=arguments,
            ),
        ))

    return calls


def chat(model=None, messages=None, tools=None, **kwargs):
    del model, kwargs

    with _lock:
        runtime = _load_model()
        tokenizer = runtime.tokenizer
        tokenizer.truncation_side = "left"
        conversation = _prepare_messages(messages or [])
        active_tools = _compact_tools(tools)

        try:
            prompt = tokenizer.apply_chat_template(
                conversation,
                tools=active_tools,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            prompt = tokenizer.apply_chat_template(
                conversation,
                tokenize=False,
                add_generation_prompt=True,
            )

        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=max(MAX_INPUT_TOKENS, 8192),
        )

        device = getattr(runtime, "device", torch.device("cuda:0"))
        inputs = {key: value.to(device) for key, value in inputs.items()}

        with torch.inference_mode():
            output = runtime.generate(
                inputs["input_ids"],
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                use_cache=True,
                return_dict_in_generate=True,
            )

        new_tokens = output.sequences[
            :, inputs["input_ids"].shape[1]:
        ]

        text = tokenizer.batch_decode(
            new_tokens,
            skip_special_tokens=False,
        )[0].strip()

        calls = _extract_tool_calls(text, tools)

        if calls:
            message = Message(
                role="assistant",
                content="",
                tool_calls=calls,
            )
        else:
            text = re.sub(
                r"<\|im_end\|>|<\|endoftext\|>|<\|fim_suffix\|>",
                "",
                text,
            ).strip()

            message = Message(
                role="assistant",
                content=text,
            )

        return Response(message=message)

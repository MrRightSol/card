"""Model capability definitions and request builder/helpers.

Centralize model/endpoint capability info and a helper to build and send
requests to the OpenAI client in a safe, model-aware manner.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

RESPONSES_PARAMS = {
    "required": {"model", "input"},
    "optional": {"temperature", "top_p", "stop", "seed", "metadata", "response_format", "tools", "tool_choice", "max_output_tokens"},
}

CHAT_PARAMS = {
    "required": {"model", "messages"},
    "optional": {"temperature", "top_p", "stop", "response_format", "tools", "tool_choice", "functions", "function_call", "max_tokens"},
}

# Per-model capabilities. Extend as you learn more about tenant/model behavior.
MODEL_CAPS = {
    "gpt-5-mini": {
        "endpoint": "responses",
        "supports_json_mode": True,
        "supports_json_schema": True,
        "supports_tools": True,
        "supports_vision": False,
        "token_param": "max_output_tokens",
    },
    "gpt-4o": {
        "endpoint": "responses",
        "supports_json_mode": True,
        "supports_json_schema": True,
        "supports_tools": True,
        "supports_vision": True,
        "supports_audio": True,
        "token_param": "max_output_tokens",
    },
    "gpt-4o-mini": {
        "endpoint": "responses",
        "supports_json_mode": True,
        "supports_json_schema": True,
        "supports_tools": True,
        "supports_vision": True,
        "token_param": "max_output_tokens",
    },
    "gpt-4.1": {
        "endpoint": "chat",
        "supports_json_mode": True,
        "supports_tools": True,
        "token_param": "max_tokens",
    },
}


def build_request(model: str, messages_or_input: Any, **kwargs) -> Tuple[str, Dict[str, Any]]:
    """Build a request payload and choose endpoint based on MODEL_CAPS.

    Returns (endpoint, payload) where endpoint is either 'responses' or 'chat'.
    """
    caps = MODEL_CAPS.get(model, {"endpoint": "responses", "token_param": "max_output_tokens"})
    endpoint = caps.get("endpoint", "responses")

    if endpoint == "responses":
        payload: Dict[str, Any] = {"model": model, "input": messages_or_input}
        allowed = RESPONSES_PARAMS["optional"]
        token_key = caps.get("token_param", "max_output_tokens")
    else:
        payload = {"model": model, "messages": messages_or_input}
        allowed = CHAT_PARAMS["optional"]
        token_key = caps.get("token_param", "max_tokens")

    # move max_tokens into the correct key
    if "max_tokens" in kwargs and token_key != "max_tokens":
        kwargs[token_key] = kwargs.pop("max_tokens")

    # filter kwargs
    for k, v in list(kwargs.items()):
        if k in allowed:
            payload[k] = v
        # drop legacy functions if tools present
        if k == 'functions' and 'tools' in kwargs:
            kwargs.pop('functions', None)

    return endpoint, payload


def send_model_request(client: Any, model: str, messages_or_input: Any, **kwargs) -> Any:
    """Send a model request using the appropriate client method.

    Tries the Responses API first when MODEL_CAPS prefers it, falling back
    to chat.completions.create if necessary.
    """
    endpoint, payload = build_request(model, messages_or_input, **kwargs)

    # prefer responses.create if available and endpoint says so
    if endpoint == 'responses' and hasattr(client, 'responses'):
        try:
            # If we have 'functions' convert to 'tools' shape some endpoints expect
            if 'functions' in payload and 'tools' not in payload:
                payload['tools'] = [{'type': 'function', 'function': f} for f in payload.get('functions', [])]
            return client.responses.create(**payload)
        except Exception:
            # fall through to chat completion fallback
            pass

    # fallback: map 'input' -> 'messages' if needed
    if 'messages' not in payload and 'input' in payload:
        inp = payload.pop('input')
        # if input is a list of role/content dicts, use as messages, else wrap as user message
        if isinstance(inp, list) and all(isinstance(i, dict) and 'role' in i and 'content' in i for i in inp):
            payload['messages'] = inp
        else:
            payload['messages'] = [{'role': 'user', 'content': inp}]

    # ensure token param key name compatibility
    if 'max_output_tokens' in payload and 'max_tokens' not in payload:
        payload['max_tokens'] = payload.pop('max_output_tokens')

    # Finally call chat completions
    # Normalize tooling: many parts of code build 'tools' with a function-like schema.
    # The Chat API expects 'functions' while some Calls/Responses variants accept 'tools'.
    if 'tools' in payload:
        tools = payload.pop('tools')
        # map to 'functions' suitable for chat completions
        funcs = []
        for t in tools:
            # if t already contains a nested 'function' key, use that; else build one
            if isinstance(t, dict) and 'function' in t and isinstance(t['function'], dict):
                funcs.append(t['function'])
            else:
                # expected keys: name, description, parameters
                fn = {}
                if isinstance(t, dict) and 'name' in t:
                    fn['name'] = t['name']
                if isinstance(t, dict) and 'description' in t:
                    fn['description'] = t['description']
                if isinstance(t, dict) and 'parameters' in t:
                    fn['parameters'] = t['parameters']
                if fn:
                    funcs.append(fn)
        if funcs:
            payload['functions'] = funcs
            # also keep a 'tools' wrapper for endpoints that expect the tools[0].function shape
            if 'tools' not in payload:
                payload['tools'] = [{'type': 'function', 'function': f} for f in funcs]
    # Map tool_choice -> function_call if present
    if 'tool_choice' in payload:
        tc = payload.pop('tool_choice')
        # support shape: {'type':'function', 'function': {'name': '...'}} or {'function': {'name': '...'}} or string
        if isinstance(tc, dict):
            func = tc.get('function') or tc.get('function_name')
            if isinstance(func, dict) and 'name' in func:
                payload['function_call'] = {'name': func['name']}
            elif isinstance(func, str):
                payload['function_call'] = {'name': func}
        elif isinstance(tc, str):
            payload['function_call'] = {'name': tc}

    if hasattr(client, 'chat') and hasattr(client.chat, 'completions'):
        return client.chat.completions.create(**payload)

    # Very last resort: try client.responses.create again
    if hasattr(client, 'responses'):
        return client.responses.create(**payload)

    raise RuntimeError('No suitable client method found to send model request')


def probe_feature(client: Any, model: str, feature: str) -> bool:
    try:
        if feature == "json_mode":
            endpoint, payload = build_request(
                model,
                [{"role": "user", "content": "respond with a JSON object with key ok:true"}] if MODEL_CAPS.get(model, {}).get('endpoint') == 'chat' else 'Respond with JSON: {"ok":true}',
                response_format={"type": "json_object"},
                temperature=0,
                **({"max_tokens": 32} if MODEL_CAPS.get(model, {}).get('endpoint') == 'chat' else {"max_output_tokens": 32})
            )
        elif feature == "tools":
            tool = {"type": "function", "function": {"name": "ping", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}
            endpoint, payload = build_request(
                model,
                [{"role": "user", "content": "call ping"}] if MODEL_CAPS.get(model, {}).get('endpoint') == 'chat' else 'call ping',
                tools=[tool],
                tool_choice="auto",
                temperature=0,
                **({"max_tokens": 32} if MODEL_CAPS.get(model, {}).get('endpoint') == 'chat' else {"max_output_tokens": 32})
            )
        else:
            return False

        # dispatch a minimal test
        if endpoint == 'responses' and hasattr(client, 'responses'):
            client.responses.create(**payload)
        else:
            client.chat.completions.create(**payload)
        return True
    except Exception:
        return False

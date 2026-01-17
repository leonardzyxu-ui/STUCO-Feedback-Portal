import base64
import json

import requests
from flask import current_app

from ...config import AppConfig


class AIProviderError(Exception):
    pass


def _value_from_config(config, key, default=None):
    if config is None:
        return current_app.config.get(key, default)
    if isinstance(config, dict):
        return config.get(key, default)
    if isinstance(config, AppConfig):
        return getattr(config, key.lower(), default)
    return getattr(config, key, default)


def _strip_images_for_text(messages):
    cleaned = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            content = " ".join(part for part in text_parts if part)
        cleaned.append({"role": message.get("role", "user"), "content": content})
    return cleaned


class BaseProvider:
    name = "base"
    supports_vision = False

    def __init__(self, api_key, model, api_url, timeout, max_tokens):
        self.api_key = api_key
        self.model = model
        self.api_url = api_url
        self.timeout = timeout
        self.max_tokens = max_tokens

    def is_configured(self):
        return bool(self.api_key)

    def chat(self, messages, temperature=0.0, max_tokens=None, response_format=None):
        raise NotImplementedError

    def multimodal_chat(self, text, images, temperature=0.2, max_tokens=None):
        raise AIProviderError(f"Provider '{self.name}' does not support multimodal inputs.")


class DeepSeekProvider(BaseProvider):
    name = "deepseek"

    def chat(self, messages, temperature=0.0, max_tokens=None, response_format=None):
        if not self.is_configured():
            raise AIProviderError("DeepSeek API key missing.")
        payload = {
            "model": self.model,
            "messages": _strip_images_for_text(messages),
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        response = requests.post(
            self.api_url, headers=headers, json=payload, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


class OpenAIProvider(BaseProvider):
    name = "openai"
    supports_vision = True

    def chat(self, messages, temperature=0.0, max_tokens=None, response_format=None):
        if not self.is_configured():
            raise AIProviderError("OpenAI API key missing.")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        response = requests.post(
            self.api_url, headers=headers, json=payload, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def multimodal_chat(self, text, images, temperature=0.2, max_tokens=None):
        if not self.supports_vision:
            return super().multimodal_chat(text, images, temperature, max_tokens)
        content = []
        if text:
            content.append({"type": "text", "text": text})
        for image in images or []:
            if image.get("type") == "url":
                content.append({"type": "image_url", "image_url": {"url": image.get("data")}})
            elif image.get("type") == "base64":
                mime = image.get("mime_type", "image/png")
                data = image.get("data", "")
                content.append(
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}
                )
        messages = [{"role": "user", "content": content}]
        return self.chat(
            messages, temperature=temperature, max_tokens=max_tokens or self.max_tokens
        )


class GeminiProvider(BaseProvider):
    name = "gemini"
    supports_vision = True

    def chat(self, messages, temperature=0.0, max_tokens=None, response_format=None):
        if not self.is_configured():
            raise AIProviderError("Gemini API key missing.")
        contents = []
        for message in messages:
            role = "user" if message.get("role") in {"user", "system"} else "model"
            content = message.get("content", "")
            if isinstance(content, list):
                parts = [
                    {"text": item.get("text", "")}
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
            else:
                parts = [{"text": str(content)}]
            contents.append({"role": role, "parts": parts})
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens or self.max_tokens,
            },
        }
        if response_format:
            payload["generationConfig"]["response_mime_type"] = "application/json"
        url = f"{self.api_url}/{self.model}:generateContent?key={self.api_key}"
        response = requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise AIProviderError("Gemini response missing candidates.")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts)

    def multimodal_chat(self, text, images, temperature=0.2, max_tokens=None):
        if not self.supports_vision:
            return super().multimodal_chat(text, images, temperature, max_tokens)
        parts = []
        if text:
            parts.append({"text": text})
        for image in images or []:
            if image.get("type") == "base64":
                mime = image.get("mime_type", "image/png")
                data = image.get("data", "")
                parts.append({"inline_data": {"mime_type": mime, "data": data}})
            elif image.get("type") == "url":
                data = _fetch_and_encode_image(image.get("data"))
                parts.append({"inline_data": {"mime_type": data["mime_type"], "data": data["data"]}})
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens or self.max_tokens,
            },
        }
        url = f"{self.api_url}/{self.model}:generateContent?key={self.api_key}"
        response = requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise AIProviderError("Gemini response missing candidates.")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts)


def _fetch_and_encode_image(url):
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    mime_type = response.headers.get("Content-Type", "image/png")
    data = base64.b64encode(response.content).decode("ascii")
    return {"mime_type": mime_type, "data": data}


def get_provider(config=None, override=None):
    provider_name = (override or _value_from_config(config, "AI_PROVIDER", "deepseek")).lower()
    timeout = _value_from_config(config, "AI_TIMEOUT", 60)
    max_tokens = _value_from_config(config, "AI_MAX_TOKENS", 800)

    if provider_name == "openai":
        return OpenAIProvider(
            api_key=_value_from_config(config, "OPENAI_API_KEY"),
            model=_value_from_config(config, "OPENAI_MODEL", "gpt-5.2"),
            api_url=_value_from_config(
                config, "OPENAI_API_URL", "https://api.openai.com/v1/chat/completions"
            ),
            timeout=timeout,
            max_tokens=max_tokens,
        )
    if provider_name == "gemini":
        return GeminiProvider(
            api_key=_value_from_config(config, "GEMINI_API_KEY"),
            model=_value_from_config(config, "GEMINI_MODEL", "gemini-3-pro-preview"),
            api_url=_value_from_config(
                config, "GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta/models"
            ),
            timeout=timeout,
            max_tokens=max_tokens,
        )
    return DeepSeekProvider(
        api_key=_value_from_config(config, "DEEPSEEK_API_KEY"),
        model=_value_from_config(config, "DEEPSEEK_MODEL", "deepseek-v3.2"),
        api_url=_value_from_config(
            config, "DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"
        ),
        timeout=timeout,
        max_tokens=max_tokens,
    )


def parse_json_response(content):
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise AIProviderError(f"Failed to parse JSON response: {exc}")

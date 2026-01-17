from .providers import AIProviderError, get_provider


def run_multimodal_chat(text, images=None, provider=None, temperature=0.2, max_tokens=None):
    provider = provider or get_provider()
    if not provider.is_configured():
        raise AIProviderError("AI provider key missing.")
    return provider.multimodal_chat(text, images or [], temperature=temperature, max_tokens=max_tokens)

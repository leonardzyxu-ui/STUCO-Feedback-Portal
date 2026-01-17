import re

from .providers import AIProviderError, get_provider, parse_json_response


MOCK_TOXICITY_REGEXES = [
    re.compile(pattern)
    for pattern in [
        r"\bfuck\b",
        r"\bshit\b",
        r"\bbitch\b",
        r"\bass\b",
        r"\bdamn\b",
        r"\bidiot\b",
        r"\bstupid\b",
        r"\bterrible teacher\b",
        r"\bhorrible person\b",
        r"\bworst teacher\b",
        r"\bbully\b",
        r"\bbullying\b",
        r"\bthreat\b",
        r"\bkill\b",
    ]
]


def run_mock_toxicity_check(text_input):
    text_lower = text_input.lower()
    is_inappropriate = any(regex.search(text_lower) for regex in MOCK_TOXICITY_REGEXES)
    toxicity_score = 0.95 if is_inappropriate else 0.0
    return {"toxicity_score": toxicity_score, "is_inappropriate": is_inappropriate}


def run_toxicity_check(text_input, provider=None):
    provider = provider or get_provider()
    if not provider.is_configured():
        print("WARNING: AI provider key missing. Using mock toxicity checks.")
        return run_mock_toxicity_check(text_input)

    system_prompt = (
        "You are an extremely strict content moderation expert for a school feedback system. "
        "Your job is to protect teachers from ANY personal insults, profanity, or abusive language. "
        "Your response MUST be in a single, valid JSON object format with two keys: 'is_inappropriate' "
        "(boolean) and 'toxicity_score' (float 0.0-1.0). "
        "CRITICAL: Set 'is_inappropriate' to true if the text contains any profanity, personal insults, "
        "bullying, or threats. Be extremely sensitive and err on the side of caution."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text_input},
    ]
    try:
        content = provider.chat(
            messages,
            temperature=0.0,
            max_tokens=120,
            response_format={"type": "json_object"},
        )
        result = parse_json_response(content)
        is_inappropriate = bool(result.get("is_inappropriate", False))
        toxicity_score = float(result.get("toxicity_score", 0.0))
        if is_inappropriate and toxicity_score < 0.8:
            toxicity_score = 0.95
        return {"toxicity_score": toxicity_score, "is_inappropriate": is_inappropriate}
    except (AIProviderError, ValueError) as exc:
        print(f"CRITICAL TOXICITY CHECK ERROR: {exc}. Defaulting to 'inappropriate'.")
        return {"toxicity_score": 1.0, "is_inappropriate": True}

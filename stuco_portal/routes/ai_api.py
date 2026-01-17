from flask import Blueprint, current_app, jsonify, request, g

from ..auth import auth_required
from ..services.ai.multimodal import run_multimodal_chat
from ..services.ai.providers import AIProviderError, get_provider

bp = Blueprint("ai_api", __name__)


@bp.route("/api/ai/multimodal", methods=["POST"])
@auth_required(role="stuco_admin")
def multimodal_chat():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400

    text = (data.get("text") or "").strip()
    images = data.get("images") or []
    provider_override = (data.get("provider") or "").strip().lower() or None
    model_override = (data.get("model") or "").strip() or None
    temperature = data.get("temperature")
    max_tokens = data.get("max_tokens")

    if not text and not images:
        return jsonify({"error": "Provide text or images for multimodal chat."}), 400

    if not isinstance(images, list):
        return jsonify({"error": "Images must be a list."}), 400

    for image in images:
        if not isinstance(image, dict) or "type" not in image or "data" not in image:
            return jsonify({"error": "Each image must include type and data."}), 400
        if image.get("type") not in {"url", "base64"}:
            return jsonify({"error": "Image type must be 'url' or 'base64'."}), 400

    provider = get_provider(override=provider_override)
    if model_override:
        provider.model = model_override

    try:
        temperature = float(temperature) if temperature is not None else 0.2
    except (TypeError, ValueError):
        temperature = 0.2
    try:
        max_tokens = int(max_tokens) if max_tokens is not None else current_app.config.get(
            "AI_MAX_TOKENS", 800
        )
    except (TypeError, ValueError):
        max_tokens = current_app.config.get("AI_MAX_TOKENS", 800)

    try:
        if images and not provider.supports_vision:
            return jsonify({"error": f"Provider '{provider.name}' does not support images."}), 400
        if images:
            output = run_multimodal_chat(
                text, images=images, provider=provider, temperature=temperature, max_tokens=max_tokens
            )
        else:
            output = provider.chat(
                [{"role": "user", "content": text}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return jsonify(
            {
                "provider": provider.name,
                "model": provider.model,
                "output": output,
                "requested_by": g.user.id,
            }
        )
    except AIProviderError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        print(f"ERROR: Multimodal chat failed: {exc}")
        return jsonify({"error": "Multimodal chat failed."}), 500

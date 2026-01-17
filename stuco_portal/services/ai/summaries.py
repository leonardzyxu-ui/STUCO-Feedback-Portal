import html as html_lib
import random
import re

from flask import current_app

from ...extensions import db
from ...models import CategorySummary, Feedback, TeacherSummary
from .providers import AIProviderError, get_provider, parse_json_response

BULLET_REGEX = re.compile(r"<li>(.*?)</li>", re.IGNORECASE | re.DOTALL)


def extract_bullets_from_html(summary_html):
    if not summary_html:
        return []
    matches = BULLET_REGEX.findall(summary_html)
    if matches:
        bullets = []
        for match in matches:
            text = re.sub(r"<[^>]+>", "", match)
            text = html_lib.unescape(text).strip()
            if text:
                bullets.append(text)
        return bullets
    text = re.sub(r"<[^>]+>", " ", summary_html)
    text = html_lib.unescape(text)
    lines = [line.strip(" -\t") for line in text.splitlines()]
    return [line for line in lines if line]


def get_summary_bullets(summary_entry, is_positive):
    if not summary_entry:
        return []
    bullets = (
        summary_entry.raw_positive_bullets
        if is_positive
        else summary_entry.raw_actionable_bullets
    )
    if bullets:
        return bullets
    summary_html = (
        summary_entry.latest_positive_summary
        if is_positive
        else summary_entry.latest_actionable_summary
    )
    return extract_bullets_from_html(summary_html)


def render_bullets_html(bullets):
    safe_items = [html_lib.escape(item) for item in bullets]
    return "<ul>" + "".join(f"<li>{item}</li>" for item in safe_items) + "</ul>"


def generate_mock_summary(target_id, summary_type="teacher"):
    print(f"MOCK SUMMARY: Generating FAST, SAFE summary for {summary_type} ID: {target_id}.")
    mock_positives = [
        "Students find the class activities engaging and fun.",
        "The teacher's enthusiasm for the subject is appreciated.",
        "Clear explanations help students understand complex topics.",
        "Students feel supported and comfortable asking questions.",
    ]
    mock_actionables = [
        "Consider reviewing the pacing of homework assignments.",
        "Some students would appreciate more in-class practice time.",
        "Ensure test content directly aligns with in-class material.",
        "Posting slides or resources in advance would be helpful.",
    ]

    if summary_type == "teacher":
        summary_entry = db.session.get(TeacherSummary, int(target_id))
    else:
        summary_entry = db.session.get(CategorySummary, target_id)

    if summary_entry:
        positive_bullets = list(summary_entry.raw_positive_bullets or [])
        actionable_bullets = list(summary_entry.raw_actionable_bullets or [])
    else:
        positive_bullets = []
        actionable_bullets = []

    if not positive_bullets:
        positive_bullets = [random.choice(mock_positives)]
    if not actionable_bullets:
        actionable_bullets = [random.choice(mock_actionables)]

    if random.choice([True, False]):
        new_pos = random.choice(mock_positives)
        if new_pos not in positive_bullets:
            positive_bullets.append(new_pos)
    else:
        new_act = random.choice(mock_actionables)
        if new_act not in actionable_bullets:
            actionable_bullets.append(new_act)

    positive_summary_html = "<ul>" + "".join(
        f"<li>{item}</li>" for item in positive_bullets
    ) + "</ul>"
    actionable_summary_html = "<ul>" + "".join(
        f"<li>{item}</li>" for item in actionable_bullets
    ) + "</ul>"

    if summary_type == "teacher":
        new_summary_entry = TeacherSummary(
            teacher_id=int(target_id),
            latest_positive_summary=positive_summary_html,
            latest_actionable_summary=actionable_summary_html,
            raw_positive_bullets=positive_bullets,
            raw_actionable_bullets=actionable_bullets,
        )
    else:
        new_summary_entry = CategorySummary(
            category_name=target_id,
            latest_positive_summary=positive_summary_html,
            latest_actionable_summary=actionable_summary_html,
            raw_positive_bullets=positive_bullets,
            raw_actionable_bullets=actionable_bullets,
        )

    db.session.merge(new_summary_entry)
    db.session.commit()
    print(f"MOCK SUMMARY: Fast, SAFE summary updated for {summary_type} ID: {target_id}.")


def _normalize_bullets(bullets):
    if not bullets:
        return []
    if isinstance(bullets, list):
        return [str(item).strip() for item in bullets if str(item).strip()]
    return [str(bullets).strip()]


def run_teacher_summary(target_id, provider=None):
    teacher_id = int(target_id)
    provider = provider or get_provider()
    deepthink = current_app.config.get("DEEPTHINK_OR_NOT", False)
    if not deepthink or not provider.is_configured():
        print("INFO: Real summaries disabled or provider missing. Running MOCK teacher summary.")
        generate_mock_summary(teacher_id, "teacher")
        return

    print(f"REAL AI SUMMARY: Generating holistic report for teacher_id {teacher_id}...")

    past_feedback = Feedback.query.filter(
        Feedback.teacher_id == teacher_id,
        Feedback.is_inappropriate.is_(False),
        Feedback.is_summary_approved.is_(True),
    ).all()

    feedback_entries = [f.feedback_text for f in past_feedback]

    if not feedback_entries:
        print("INFO: No feedback to summarize for teacher. Clearing summary.")
        summary_entry = TeacherSummary(
            teacher_id=teacher_id,
            latest_positive_summary="<ul><li>No feedback available.</li></ul>",
            latest_actionable_summary="<ul><li>No feedback available.</li></ul>",
            raw_positive_bullets=[],
            raw_actionable_bullets=[],
        )
        db.session.merge(summary_entry)
        db.session.commit()
        return

    combined_text = "\n---\n".join(feedback_entries)

    system_prompt = (
        "You are an expert educational analyst. Your task is to synthesize a list of raw, "
        "anonymous student feedback into a holistic and cumulative report for the teacher. "
        "Your response MUST be in a single, valid JSON object format. "
        "The JSON object must have exactly two keys: 'positive_highlights' and 'actionable_growth'. "
        "Each key must contain a list (an array) of bullet-point strings. "
        "CRITICAL RULES: BE COMPREHENSIVE, DO NOT FORGET older points, consolidate similar points, "
        "and keep growth points constructive. Do not use markdown."
    )
    user_prompt = f"Here is the collected feedback:\n\n{combined_text}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        content = provider.chat(messages, response_format={"type": "json_object"})
        summary_json = parse_json_response(content)
        positive_bullets = _normalize_bullets(summary_json.get("positive_highlights", []))
        actionable_bullets = _normalize_bullets(summary_json.get("actionable_growth", []))
        positive_summary_html = render_bullets_html(positive_bullets)
        actionable_summary_html = render_bullets_html(actionable_bullets)
        summary_entry = TeacherSummary(
            teacher_id=teacher_id,
            latest_positive_summary=positive_summary_html,
            latest_actionable_summary=actionable_summary_html,
            raw_positive_bullets=positive_bullets,
            raw_actionable_bullets=actionable_bullets,
        )
        db.session.merge(summary_entry)
        db.session.commit()
    except AIProviderError as exc:
        db.session.rollback()
        print(f"CRITICAL AI ERROR (Teacher Summary): {exc}")
        raise


def run_category_summary(target_id, provider=None):
    category_name = target_id
    provider = provider or get_provider()
    deepthink = current_app.config.get("DEEPTHINK_OR_NOT", False)
    if not deepthink or not provider.is_configured():
        print(
            f"INFO: Real summaries disabled or provider missing. Running MOCK category summary for '{category_name}'."
        )
        generate_mock_summary(category_name, "category")
        return

    print(f"REAL AI SUMMARY: Generating holistic report for category '{category_name}'...")

    past_feedback = Feedback.query.filter(
        Feedback.category == category_name,
        Feedback.is_inappropriate.is_(False),
        Feedback.is_summary_approved.is_(True),
    ).all()

    feedback_entries = [f.feedback_text for f in past_feedback]

    if not feedback_entries:
        print(f"INFO: No feedback to summarize for category '{category_name}'. Clearing summary.")
        summary_entry = CategorySummary(
            category_name=category_name,
            latest_positive_summary="<ul><li>No feedback available.</li></ul>",
            latest_actionable_summary="<ul><li>No feedback available.</li></ul>",
            raw_positive_bullets=[],
            raw_actionable_bullets=[],
        )
        db.session.merge(summary_entry)
        db.session.commit()
        return

    combined_text = "\n---\n".join(feedback_entries)

    system_prompt = (
        "You are an expert operational analyst for a school's Student Council (STUCO). "
        "Your task is to synthesize raw, anonymous student feedback about a specific school category "
        f"into a holistic and cumulative report for STUCO admins. The category is: {category_name.upper()}. "
        "Your response MUST be in a single, valid JSON object format. "
        "The JSON object must have exactly two keys: 'positive_highlights' and 'actionable_growth'. "
        "Each key must contain a list (an array) of bullet-point strings. "
        "CRITICAL RULES: BE COMPREHENSIVE, DO NOT FORGET older points, consolidate similar points, "
        "and keep growth points constructive. Do not use markdown."
    )
    user_prompt = f"Here is the collected feedback for {category_name}:\n\n{combined_text}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        content = provider.chat(messages, response_format={"type": "json_object"})
        summary_json = parse_json_response(content)
        positive_bullets = _normalize_bullets(summary_json.get("positive_highlights", []))
        actionable_bullets = _normalize_bullets(summary_json.get("actionable_growth", []))
        positive_summary_html = render_bullets_html(positive_bullets)
        actionable_summary_html = render_bullets_html(actionable_bullets)
        summary_entry = CategorySummary(
            category_name=category_name,
            latest_positive_summary=positive_summary_html,
            latest_actionable_summary=actionable_summary_html,
            raw_positive_bullets=positive_bullets,
            raw_actionable_bullets=actionable_bullets,
        )
        db.session.merge(summary_entry)
        db.session.commit()
    except AIProviderError as exc:
        db.session.rollback()
        print(f"CRITICAL AI ERROR (Category Summary): {exc}")
        raise

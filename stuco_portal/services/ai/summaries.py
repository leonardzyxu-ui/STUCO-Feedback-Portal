import html as html_lib
import random
import re
from datetime import date, datetime, timedelta

from flask import current_app

from ...extensions import db
from ...models import CategorySummary, Feedback, MonthlyDigest, TeacherSummary
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


def month_key_for_date(target_date):
    return f"{target_date.year:04d}-{target_date.month:02d}"


def get_month_date_range(target_date):
    start_date = date(target_date.year, target_date.month, 1)
    next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    end_date = next_month - timedelta(days=1)
    return start_date, end_date


def is_last_day_of_month(target_date):
    _, end_date = get_month_date_range(target_date)
    return target_date == end_date


def generate_mock_monthly_digest(month_key, feedback_count):
    print(f"MOCK SUMMARY: Generating monthly digest for {month_key}.")
    mock_positives = [
        "Students appreciated clearer assignment expectations.",
        "Positive feedback highlighted supportive classroom environments.",
        "Class discussions felt more engaging this month.",
        "Students recognized improved feedback turnaround times.",
    ]
    mock_actionables = [
        "Continue improving pacing for complex units.",
        "Provide more practice examples before assessments.",
        "Add reminders for upcoming deadlines in class.",
        "Expand access to supplemental study materials.",
    ]
    positive_bullets = [random.choice(mock_positives)]
    actionable_bullets = [random.choice(mock_actionables)]
    if feedback_count > 3:
        positive_bullets.append(random.choice(mock_positives))
    if feedback_count > 5:
        actionable_bullets.append(random.choice(mock_actionables))
    return positive_bullets, actionable_bullets


def run_monthly_digest(target_date=None, provider=None):
    target_date = target_date or date.today()
    month_key = month_key_for_date(target_date)
    existing = db.session.get(MonthlyDigest, month_key)
    if existing:
        return existing

    start_date, end_date = get_month_date_range(target_date)
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    feedback_entries = (
        Feedback.query.filter(
            Feedback.created_at >= start_dt,
            Feedback.created_at <= end_dt,
            Feedback.is_inappropriate.is_(False),
            Feedback.is_summary_approved.is_(True),
        )
        .order_by(Feedback.created_at)
        .all()
    )
    feedback_texts = [item.feedback_text for item in feedback_entries]
    feedback_count = len(feedback_texts)

    if not feedback_texts:
        summary_entry = MonthlyDigest(
            month_key=month_key,
            start_date=start_date,
            end_date=end_date,
            positive_bullets=["No approved feedback was submitted this month."],
            actionable_bullets=["Encourage students to submit feedback before month end."],
            feedback_count=0,
        )
        db.session.merge(summary_entry)
        db.session.commit()
        return summary_entry

    provider = provider or get_provider()
    deepthink = current_app.config.get("DEEPTHINK_OR_NOT", False)
    if not deepthink or not provider.is_configured():
        positive_bullets, actionable_bullets = generate_mock_monthly_digest(
            month_key, feedback_count
        )
        summary_entry = MonthlyDigest(
            month_key=month_key,
            start_date=start_date,
            end_date=end_date,
            positive_bullets=positive_bullets,
            actionable_bullets=actionable_bullets,
            feedback_count=feedback_count,
        )
        db.session.merge(summary_entry)
        db.session.commit()
        return summary_entry

    combined_text = "\n---\n".join(feedback_texts)

    system_prompt = (
        "You are an expert educational analyst. Summarize approved, anonymous student feedback "
        "into a monthly digest for STUCO leaders. Respond ONLY with a valid JSON object with "
        "exactly two keys: 'positive_highlights' and 'actionable_growth'. Each key must contain "
        "a list (array) of concise bullet strings. Avoid naming individual students or teachers. "
        "Keep the list focused and use plain language. Do not use markdown."
    )
    user_prompt = (
        f"Monthly feedback window: {start_date.isoformat()} to {end_date.isoformat()}.\n\n"
        f"Feedback entries:\n{combined_text}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        content = provider.chat(messages, response_format={"type": "json_object"})
        summary_json = parse_json_response(content)
        positive_bullets = _normalize_bullets(summary_json.get("positive_highlights", []))
        actionable_bullets = _normalize_bullets(summary_json.get("actionable_growth", []))
        summary_entry = MonthlyDigest(
            month_key=month_key,
            start_date=start_date,
            end_date=end_date,
            positive_bullets=positive_bullets,
            actionable_bullets=actionable_bullets,
            feedback_count=feedback_count,
        )
        db.session.merge(summary_entry)
        db.session.commit()
        return summary_entry
    except AIProviderError as exc:
        db.session.rollback()
        print(f"CRITICAL AI ERROR (Monthly Digest): {exc}")
        raise

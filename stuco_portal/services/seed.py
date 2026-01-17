import os

from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import (
    Announcement,
    Category,
    ClarificationRequest,
    Feedback,
    SummaryJobQueue,
    Teacher,
    TeacherSummary,
    User,
)
from .ai.moderation import run_toxicity_check
from .audit import record_feedback_status


def seed_data():
    """Populates the database only if it is empty."""
    seeded_users = False
    if db.session.query(User).first() is None:
        print("INFO: Database is empty. Seeding initial data...")
        demo_student_password = os.getenv("DEMO_STUDENT_PASSWORD", "student123")
        demo_teacher_password = os.getenv("DEMO_TEACHER_PASSWORD", "teacher123")
        demo_admin_password = os.getenv("DEMO_ADMIN_PASSWORD", "admin123")
        db.session.add_all(
            [
                User(
                    id=1,
                    azure_oid="student_1",
                    email="student@test.com",
                    name="Student A",
                    role="student",
                    password_hash=generate_password_hash(demo_student_password),
                ),
                User(
                    id=2,
                    azure_oid="teacher_1",
                    email="harper@test.com",
                    name="Mr. Harper",
                    role="teacher",
                    password_hash=generate_password_hash(demo_teacher_password),
                ),
                User(
                    id=3,
                    azure_oid="admin_1",
                    email="chen@test.com",
                    name="Ms. Chen",
                    role="stuco_admin",
                    password_hash=generate_password_hash(demo_admin_password),
                ),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                Teacher(
                    id=1,
                    user_id=2,
                    name="Mr. Harper",
                    email="harper@test.com",
                    year_6=True,
                    year_7=True,
                    year_8=False,
                    is_active=True,
                ),
                Teacher(
                    id=2,
                    user_id=None,
                    name="Ms. Williams",
                    email="williams@test.com",
                    year_6=True,
                    year_7=False,
                    year_8=True,
                    is_active=True,
                ),
                Teacher(
                    id=3,
                    user_id=None,
                    name="Ms. Chen (Admin)",
                    email="chen@test.com",
                    year_6=True,
                    year_7=True,
                    year_8=True,
                    is_active=True,
                ),
            ]
        )
        db.session.commit()
        seeded_users = True

        f1 = Feedback(
            id=1,
            teacher_id=1,
            year_level_submitted="Year 7",
            feedback_text="Mr. Harper is a great teacher! His explanations are very clear.",
            willing_to_share_name=True,
            submitted_by_user_id=1,
            category="teacher",
            rating_clarity=5,
            rating_pacing=4,
            rating_resources=5,
            rating_support=5,
        )
        f2 = Feedback(
            id=2,
            teacher_id=None,
            year_level_submitted="N/A",
            feedback_text="The cafeteria food, especially the pasta, has been excellent this week.",
            context_detail="Upper School Hot Lunch",
            willing_to_share_name=False,
            submitted_by_user_id=1,
            category="food",
        )
        f3 = Feedback(
            id=3,
            teacher_id=None,
            year_level_submitted="N/A",
            feedback_text="This teacher is a horrible bully and should be fired! I hate their lessons.",
            context_detail="Advisory",
            willing_to_share_name=False,
            submitted_by_user_id=1,
            category="other",
        )
        f4 = Feedback(
            id=4,
            teacher_id=None,
            year_level_submitted="N/A",
            feedback_text="The new uniform policy is unclear. We need more examples of what is allowed.",
            context_detail="Uniform Policy",
            willing_to_share_name=False,
            submitted_by_user_id=1,
            category="policy",
        )
        f5 = Feedback(
            id=5,
            teacher_id=1,
            year_level_submitted="Year 7",
            feedback_text="This class is a bit too fast and the homework is hard.",
            willing_to_share_name=False,
            submitted_by_user_id=1,
            category="teacher",
            rating_clarity=3,
            rating_pacing=2,
            rating_resources=3,
            rating_support=4,
        )

        db.session.add_all([f1, f2, f3, f4, f5])
        db.session.commit()

        for feedback_item in db.session.query(Feedback).filter(Feedback.status == "New").all():
            screening = run_toxicity_check(feedback_item.feedback_text)
            feedback_item.toxicity_score = screening["toxicity_score"]
            feedback_item.is_inappropriate = screening["is_inappropriate"]

            if feedback_item.is_inappropriate:
                feedback_item.status = "Screened - Escalation"
            else:
                feedback_item.status = "Approved"
                feedback_item.is_summary_approved = True

                if feedback_item.category == "teacher":
                    job = SummaryJobQueue(
                        job_type="teacher",
                        target_id=str(feedback_item.teacher_id),
                        feedback_id=feedback_item.id,
                        status="pending",
                    )
                    db.session.add(job)
                else:
                    job = SummaryJobQueue(
                        job_type="category",
                        target_id=feedback_item.category,
                        feedback_id=feedback_item.id,
                        status="pending",
                    )
                    db.session.add(job)
            record_feedback_status(feedback_item.id, None, feedback_item.status, None, note="Seeded data")

        db.session.commit()

        cr1 = ClarificationRequest(
            teacher_id=1,
            question_text=(
                "A summary mentioned 'pacing' was a problem. Could I know if this refers to the "
                "homework pacing or the in-class lecture pacing?"
            ),
            status="pending",
        )
        db.session.add(cr1)
        db.session.commit()

        f3_toxic = db.session.get(Feedback, 3)
        if f3_toxic and f3_toxic.is_inappropriate:
            print("INFO: Seeded safeguarding item (ID 3) correctly flagged for escalation.")

    if Category.query.first() is None:
        category_seed = [
            Category(
                slug="teacher",
                title="Teacher Suggestions",
                description="Share classroom feedback and ratings.",
                icon="teacher",
                context_label="Class or subject detail",
                requires_teacher=True,
                sort_order=1,
                is_active=True,
            ),
            Category(
                slug="food",
                title="Food",
                description="Menus, service, and dining flow.",
                icon="food",
                context_label="Dining hall area or specific item",
                requires_teacher=False,
                sort_order=2,
                is_active=True,
            ),
            Category(
                slug="policy",
                title="Policy",
                description="Rules, expectations, and clarity.",
                icon="policy",
                context_label="Related policy or department",
                requires_teacher=False,
                sort_order=3,
                is_active=True,
            ),
            Category(
                slug="equipment",
                title="General services",
                description="Equipment, facilities, support.",
                icon="equipment",
                context_label="Equipment or location",
                requires_teacher=False,
                sort_order=4,
                is_active=True,
            ),
            Category(
                slug="school-buses",
                title="School buses",
                description="Routes, timing, and safety.",
                icon="school-buses",
                context_label="Route, bus number, or time",
                requires_teacher=False,
                sort_order=5,
                is_active=True,
            ),
            Category(
                slug="other",
                title="Other",
                description="Anything else on your mind.",
                icon="other",
                context_label="Relevant detail (optional)",
                requires_teacher=False,
                sort_order=6,
                is_active=True,
            ),
            Category(
                slug="help",
                title="Help",
                description="Reach out for support and care.",
                icon="help",
                context_label="Who should know? (optional)",
                requires_teacher=False,
                sort_order=7,
                is_active=True,
            ),
        ]
        db.session.add_all(category_seed)
        db.session.commit()

    if Announcement.query.first() is None:
        welcome = Announcement(
            title="Welcome to the STUCO Feedback Portal",
            body=(
                "This is the new home for student voice. Submit feedback, track updates, and "
                "expect clearer follow-through."
            ),
            audience="all",
            is_active=True,
            created_by_user_id=3 if seeded_users else None,
        )
        db.session.add(welcome)
        db.session.commit()

    print("INFO: Seed data finished.")

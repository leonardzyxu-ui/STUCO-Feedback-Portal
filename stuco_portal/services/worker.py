import threading
from collections import defaultdict
from datetime import date

from ..extensions import db
from ..models import MonthlyDigest, SummaryJobQueue
from .ai.summaries import (
    is_last_day_of_month,
    month_key_for_date,
    run_category_summary,
    run_monthly_digest,
    run_teacher_summary,
)

worker_thread = None
worker_started = False
stop_worker_event = threading.Event()


def summary_worker_thread(flask_app):
    print("WORKER: Background summary worker thread started.")

    while not stop_worker_event.is_set():
        try:
            with flask_app.app_context():
                pending_jobs = (
                    SummaryJobQueue.query.filter_by(status="pending")
                    .order_by(SummaryJobQueue.created_at)
                    .all()
                )

                if is_last_day_of_month(date.today()):
                    month_key = month_key_for_date(date.today())
                    if not db.session.get(MonthlyDigest, month_key):
                        try:
                            run_monthly_digest(date.today())
                            print(f"WORKER: Monthly digest generated for {month_key}.")
                        except Exception as exc:
                            db.session.rollback()
                            print(f"WORKER: Monthly digest generation failed: {exc}")

                if not pending_jobs:
                    stop_worker_event.wait(flask_app.config.get("WORKER_SLEEP_INTERVAL", 10))
                    continue

                print(f"WORKER: Found {len(pending_jobs)} pending jobs. Batching...")

                jobs_to_run = defaultdict(list)
                for job in pending_jobs:
                    jobs_to_run[(job.job_type, job.target_id)].append(job)

                for (job_type, target_id), job_list in jobs_to_run.items():
                    print(
                        f"WORKER: Processing batch for {job_type} ID {target_id} ({len(job_list)} jobs)..."
                    )

                    try:
                        for job in job_list:
                            job.status = "processing"
                        db.session.commit()

                        if job_type == "teacher":
                            run_teacher_summary(target_id)
                        elif job_type == "category":
                            run_category_summary(target_id)

                        for job in job_list:
                            job.status = "complete"
                        db.session.commit()
                        print(f"WORKER: Batch for {job_type} ID {target_id} complete.")

                    except Exception as exc:
                        print(
                            f"WORKER: CRITICAL ERROR processing batch for {job_type} ID {target_id}. Error: {exc}"
                        )
                        db.session.rollback()
                        for job in job_list:
                            job.status = "failed"
                        db.session.commit()

            stop_worker_event.wait(flask_app.config.get("WORKER_SLEEP_INTERVAL", 10))

        except Exception as exc:
            print(f"WORKER: CATASTROPHIC FAILURE. {exc}. Restarting loop in 60s.")
            stop_worker_event.wait(60)

    print("WORKER: Background worker thread shutting down.")


def is_thread_alive(thread):
    return thread is not None and thread.is_alive()


def start_worker_thread(app):
    global worker_thread
    global worker_started
    if is_thread_alive(worker_thread):
        return False
    stop_worker_event.clear()
    worker_thread = threading.Thread(target=summary_worker_thread, args=(app,))
    worker_thread.daemon = True
    worker_thread.start()
    worker_started = True
    return True


def stop_worker_thread():
    stop_worker_event.set()
    if is_thread_alive(worker_thread):
        worker_thread.join()

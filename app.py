import atexit
import threading
import webbrowser

from stuco_portal import create_app
from stuco_portal.extensions import db
from stuco_portal.services.ai.providers import get_provider
from stuco_portal.services.db_utils import ensure_schema_updates
from stuco_portal.services.seed import seed_data
from stuco_portal.services.worker import start_worker_thread, stop_worker_thread


def open_browser(host, port):
    url = f"http://{host}:{port}/"
    try:
        webbrowser.open(url)
    except Exception as exc:
        print(f"WARNING: Could not open browser automatically: {exc}")


def main():
    app = create_app()

    provider = get_provider(config=app.config)
    if app.config.get("DEEPTHINK_OR_NOT") and not provider.is_configured():
        raise SystemExit(
            "FATAL ERROR: AI provider API key is required when DEEPTHINK_OR_NOT=True."
        )
    if not provider.is_configured():
        print("WARNING: AI provider key missing. Using mock toxicity checks and summaries.")

    with app.app_context():
        db.create_all()
        ensure_schema_updates()
        seed_data()

    if app.config.get("ENABLE_WORKER"):
        print("MAIN: Starting background worker thread...")
        start_worker_thread(app)

    if app.config.get("AUTO_OPEN_BROWSER"):
        threading.Timer(1.0, open_browser, args=(app.config["BROWSER_HOST"], app.config["PORT"])).start()

    def shutdown_worker():
        print("MAIN: Shutting down worker thread...")
        stop_worker_thread()

    atexit.register(shutdown_worker)

    print("\n--- SERVER READY ---")
    print(f"Home: http://{app.config['BROWSER_HOST']}:{app.config['PORT']}/")
    print(f"Student Feedback: http://{app.config['BROWSER_HOST']}:{app.config['PORT']}/feedback")
    print(f"Student Dashboard: http://{app.config['BROWSER_HOST']}:{app.config['PORT']}/student_dashboard")
    print(f"Teacher: http://{app.config['BROWSER_HOST']}:{app.config['PORT']}/teach_frontend.html")
    print(f"Admin: http://{app.config['BROWSER_HOST']}:{app.config['PORT']}/stuco_admin_dashboard.html")
    print("Dev shortcut: append ?mock_user_id=1/2/3 if ALLOW_MOCK_AUTH is enabled.")
    print("--------------------------------------------------")

    app.run(host=app.config.get("HOST", "0.0.0.0"), port=app.config.get("PORT", 5001), debug=False)


if __name__ == "__main__":
    main()

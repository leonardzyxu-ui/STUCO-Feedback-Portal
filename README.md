# STUCO Feedback Portal

A Flask-based feedback platform for Student Council (STUCO) to collect anonymous feedback, moderate content, and deliver AI-assisted summaries to teachers and admins.

## Features
- Three role-based dashboards: Student, Teacher, and STUCO Admin
- Student submissions across multiple categories (teacher, food, policy, equipment/GS, school buses, other, help)
- Optional teacher-specific ratings (clarity, pacing, resources, support)
- Optional contextual detail field for non-teacher categories
- Real-time toxicity screening with DeepSeek (or local mock screening when no API key)
- AI summaries for teachers and non-teacher categories (DeepSeek or mock mode)
- Teacher clarification workflow (request/resolve through admin)
- Admin moderation queue with approve/retract/delete actions
- Background summary worker with job batching to avoid redundant AI calls
- Database reset endpoint for demo workflows

## Tech Stack
- Backend: Flask, Flask-SQLAlchemy, Flask-CORS
- Database: SQLite (or any SQLAlchemy-supported database via `DATABASE_URL`)
- Frontend: Tailwind CSS (CDN), vanilla JavaScript, Chart.js
- AI: DeepSeek API for toxicity and summarization

## Quick Start
1. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. (Optional) Create a `.env` with:
   ```bash
   DEEPSEEK_API_KEY=your_key_here
   SECRET_KEY=your_secret
   ```
3. Run the server:
   ```bash
   python3 app.py
   ```

The app auto-opens the student portal in your browser. Default port is `5001`.

## Configuration
These can be set as environment variables:
- `PORT`: server port (default `5001`)
- `HOST`: bind address (default `0.0.0.0`)
- `BROWSER_HOST`: URL host used when auto-opening (default `127.0.0.1`)
- `AUTO_OPEN_BROWSER`: set to `0` or `false` to disable auto-open
- `ENABLE_WORKER`: set to `0` or `false` to disable the background worker
- `DATABASE_URL`: override the database connection string
- `DEEPSEEK_API_KEY`: enables real toxicity checks and summaries

In `app.py`, you can also tweak:
- `DEEPTHINK_OR_NOT`: enable real AI summaries
- `WORKER_SLEEP_INTERVAL`: background worker interval

## Dashboards
- Student: `http://127.0.0.1:5001/?mock_user_id=1`
- Teacher: `http://127.0.0.1:5001/teach_frontend.html?mock_user_id=2`
- Admin: `http://127.0.0.1:5001/stuco_admin_dashboard.html?mock_user_id=3`

## Database Models
- `User`: role and identity
- `Teacher`: teacher profiles and year levels
- `Feedback`: core feedback entries + ratings + moderation status + context detail
- `TeacherSummary`: AI-generated teacher summaries
- `CategorySummary`: AI-generated category summaries
- `ClarificationRequest`: teacher-to-admin questions and replies
- `SummaryJobQueue`: background jobs for summaries

## AI Behavior
- Toxicity screening runs on every submission.
- In demo mode (no `DEEPSEEK_API_KEY`), local mock checks and summaries are used.
- Approved feedback triggers a summary job; jobs are batched by target.

## Project Structure
- `app.py`: Flask app, models, AI logic, background worker
- `stu_frontend.html`: student portal
- `teach_frontend.html`: teacher dashboard
- `stuco_admin_dashboard.html`: admin dashboard
- `requirements.txt`: Python dependencies

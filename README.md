# STUCO Feedback Portal

A Flask-based feedback platform for Student Council (STUCO) to collect anonymous feedback, moderate content, and deliver AI-assisted summaries to teachers and admins.

## Features
- Session-based authentication with signup/login and invite codes for staff roles
- Dedicated home page + student feedback hub + student dashboard
- Three role-based dashboards: Student, Teacher, and STUCO Admin
- Admin-managed categories, announcements, and teacher roster
- Audit log and student status timeline for transparency
- Student submissions across multiple categories (teacher, food, policy, equipment/GS, school buses, other, help)
- Optional teacher-specific ratings (clarity, pacing, resources, support)
- Optional contextual detail field for non-teacher categories
- Real-time toxicity screening with DeepSeek V3.2 (or local mock screening when no API key)
- AI summaries for teachers and non-teacher categories (DeepSeek/OpenAI/Gemini or mock mode)
- Multimodal AI endpoint (text + images) for admin workflows
- Dedicated MCP server for agent integrations (resources + tools)
- Teacher clarification workflow (request/resolve through admin)
- Admin moderation queue with approve/retract/delete actions
- Background summary worker with job batching to avoid redundant AI calls
- Database reset endpoint for demo workflows

## Tech Stack
- Backend: Flask, Flask-SQLAlchemy, Flask-CORS
- Database: SQLite (or any SQLAlchemy-supported database via `DATABASE_URL`)
- Frontend: Tailwind CSS (CDN), vanilla JavaScript, Chart.js
- AI: DeepSeek V3.2, OpenAI gpt-5.2, Gemini gemini-3-pro-preview
- MCP: Optional MCP server for agent access

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
   OPENAI_API_KEY=your_key_here
   GEMINI_API_KEY=your_key_here
   SECRET_KEY=your_secret
   TEACHER_INVITE_CODE=teacher-code
   ADMIN_INVITE_CODE=admin-code
   ```
3. Run the server:
   ```bash
   python3 app.py
   ```
4. (Optional) Run the MCP server:
   ```bash
   python3 mcp_server.py
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
- `OPENAI_API_KEY`: enables OpenAI (gpt-5.2) summaries and multimodal chat
- `GEMINI_API_KEY`: enables Gemini (gemini-3-pro-preview) summaries and multimodal chat
- `AI_PROVIDER`: `deepseek` (default), `openai`, or `gemini`
- `DEEPSEEK_MODEL`: default `deepseek-v3.2`
- `OPENAI_MODEL`: default `gpt-5.2`
- `GEMINI_MODEL`: default `gemini-3-pro-preview`
- `AI_TIMEOUT`: request timeout in seconds (default `60`)
- `AI_MAX_TOKENS`: max tokens for AI responses (default `800`)
- `STUDENT_SIGNUP_ENABLED`: set to `0` to disable student self-signup
- `TEACHER_INVITE_CODE`: invite code required for teacher accounts
- `ADMIN_INVITE_CODE`: invite code required for STUCO admin accounts
- `ALLOW_MOCK_AUTH`: set to `0` to disable mock_user_id shortcuts
- `MCP_API_KEY`: shared key for MCP server auth
- `MCP_HOST`: MCP server bind address (default `127.0.0.1`)
- `MCP_PORT`: MCP server port (default `5002`)
- `MCP_REQUIRE_AUTH`: set to `0` to disable MCP auth
- `DEMO_STUDENT_PASSWORD`, `DEMO_TEACHER_PASSWORD`, `DEMO_ADMIN_PASSWORD`: override seeded demo passwords

You can also set:
- `DEEPTHINK_OR_NOT`: enable real AI summaries
- `WORKER_SLEEP_INTERVAL`: background worker interval

## Dashboards
- Home: `http://127.0.0.1:5001/`
- Auth: `http://127.0.0.1:5001/auth.html`
- Student Feedback Hub: `http://127.0.0.1:5001/feedback`
- Student Dashboard: `http://127.0.0.1:5001/student_dashboard`
- Teacher: `http://127.0.0.1:5001/teach_frontend.html`
- Admin: `http://127.0.0.1:5001/stuco_admin_dashboard.html`

You can still use mock auth by appending `?mock_user_id=1/2/3` when `ALLOW_MOCK_AUTH=1`.

## Demo Accounts (Seed Data)
- Student: `student@test.com` / `student123`
- Teacher: `harper@test.com` / `teacher123`
- Admin: `chen@test.com` / `admin123`

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
- In demo mode (no provider API key), local mock checks and summaries are used.
- `AI_PROVIDER` selects DeepSeek/OpenAI/Gemini for summaries and moderation.
- Approved feedback triggers a summary job; jobs are batched by target.

## Project Structure
- `app.py`: thin entrypoint for the Flask app
- `stuco_portal/`: app package (config, models, routes, services)
- `mcp_server.py`: MCP server entrypoint for agent integrations
- `stuco_portal/agents/`: starter AI agent scaffolding
- `home.html`: public landing page
- `auth.html`: login/signup
- `stu_frontend.html`: student feedback hub
- `student_dashboard.html`: student submission history
- `teach_frontend.html`: teacher dashboard
- `stuco_admin_dashboard.html`: admin dashboard
- `requirements.txt`: Python dependencies

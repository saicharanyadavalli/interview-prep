# Interview Assistant

Interview preparation platform with Google sign-in, AI doubt assistant, courses, interactive SQL environment, and personal practice tracking.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.11+, FastAPI, Uvicorn, SlowAPI |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, Lucide React |
| Database | Supabase Postgres (PostgreSQL + RLS) |
| Auth | Supabase Auth (Google OAuth) + @supabase/ssr |
| AI | Google Gemini API (SSE Streaming) |
| Storage | Cloudinary (Avatars / Assets) |

## What You Need

1. Python 3.10 or newer
2. Node.js 18+ & npm
3. A Supabase project
4. A Google OAuth client (for Supabase Auth)
5. A Gemini API key

## Project Structure

```
interview-app/
  backend/
    main.py
    requirements.txt
    load_questions_to_supabase.py
    upload_lessons_to_supabase.py
    limiter.py
    models/
    routes/
      auth.py
      questions.py
      assistant.py
      progress.py
      revisit.py
      comments.py
      profile.py
      system_design.py
      courses.py
    services/
  frontend/
    src/
      app/
      components/
      lib/
    public/
    package.json
    next.config.ts
    tsconfig.json
    postcss.config.mjs
    .env.example
  supabase_setup.sql
  AWS-EC2-DEPLOYMENT-GUIDE.md
  BACKEND_AUDIT.md
  MIGRATION_NOTES.md
  README.md
```

## Quick Start

### 1. Clone and Open

```bash
git clone <your-repo-url>
cd interview-app
```

### 2. Create Supabase Project

1. Create a new project in Supabase.
2. Open Settings -> API and copy:
   - Project URL
   - anon key
   - service_role key

### 3. Run Database Setup Script

1. Open Supabase SQL Editor.
2. Paste all contents of `supabase_setup.sql`.
3. Run it once.

This creates the required tables with Row Level Security (RLS) policies:
1. `users`
2. `user_profiles`
3. `user_progress`
4. `practice_history`
5. `user_comments`
6. `question_bank_questions`
7. `question_bank_qnum_aliases`

### 4. Configure Google Auth in Supabase

1. Go to Authentication -> Providers -> Google.
2. Add Google OAuth Client ID and Secret.
3. In Google Cloud Console, add this redirect URI:

```text
https://<your-project-ref>.supabase.co/auth/v1/callback
```

### 4.1 Configure Session And Token Expiry (1 Hour)

To keep auth sessions limited to 1 hour and align token lifetime:

1. In Supabase Dashboard, open Authentication -> Settings.
2. Set JWT expiry to 3600 seconds.
3. Save changes.

This project also applies a frontend idle timeout and signs users out after 1 hour of inactivity.

### 5. Create Backend Environment File

Create a `.env` file in `interview-app/backend/` (or at `interview-app/` root):

```env
GEMINI_API_KEY=your_gemini_api_key
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_supabase_service_role_key

# Optional for avatar upload to Cloudinary
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
CLOUDINARY_AVATAR_FOLDER=interview-prep/avatars
```

### 6. Configure Frontend Environment File

Create a `.env.local` file in `interview-app/frontend/`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
```

### 7. Run Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

API base URL:

```text
http://localhost:8000
```

### 8. Run Frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open in browser:

```text
http://localhost:3000
```

## Load Question Bank Data & Courses Data

Question APIs depend on data in `question_bank_questions`.

The loader expects JSON files in:

```text
../output/stage3_company_wise
```

From `backend` directory:

```bash
python load_questions_to_supabase.py --truncate
python upload_lessons_to_supabase.py
```

Notes:
1. `--truncate` clears question bank tables before reload.
2. Duplicate source qnums are merged into one canonical qnum.
3. Company filtering runs from `question_bank_questions.company_tags`.

## API Overview

| Method | Endpoint | Auth Required | Description |
| --- | --- | --- | --- |
| GET | `/` | No | Basic health response |
| GET | `/health` | No | Detailed environment health check |
| POST | `/auth/session` | No | Validate token and upsert user/profile |
| GET | `/questions/companies` | Yes | List available companies |
| GET | `/questions/random` | Yes | Random question by company and difficulty |
| GET | `/questions/recommend` | Yes | Recommended question |
| GET | `/questions/all` | Yes | Full list for company and difficulty |
| GET | `/questions/catalog` | Optional | Global catalog with filters |
| GET | `/questions/catalog/user` | Yes | Global catalog with user solved flags |
| GET | `/questions/by-qnum/{qnum}` | Yes | Question by qnum |
| POST | `/assistant/ask` | Yes | AI doubt assistant (SSE Streaming & Rate Limited) |
| POST | `/progress/update` | Yes | Upsert is_solved and revisit state |
| GET | `/progress/user` | Yes | User progress summary |
| GET | `/progress/status/{qnum}` | Yes | Progress status for one qnum |
| DELETE | `/progress/{qnum}` | Yes | Clear one progress row |
| GET | `/revisit` | Yes | Revisit queue |
| DELETE | `/revisit/{qnum}` | Yes | Remove one revisit row |
| POST | `/comments/add` | Yes | Add or update comment for qnum |
| GET | `/comments/{qnum}` | Yes | Get comments for qnum |
| DELETE | `/comments/{comment_id}` | Yes | Delete one comment |
| GET | `/profile/me` | Yes | Get user profile |
| PUT | `/profile/me` | Yes | Update user profile |
| POST | `/profile/avatar/upload` | Yes | Upload avatar image (Cloudinary or inline fallback) |
| GET | `/courses/` | Yes | List available interactive courses |
| GET | `/courses/{course_slug}` | Yes | Get course details and lessons |
| GET | `/courses/{course_slug}/lessons/{lesson_id}` | Yes | Get individual course lesson content |
| GET | `/courses/{course_slug}/seed-tables` | Yes | Get SQL practice seed datasets for sql.js |
| POST | `/courses/progress/mark-completed` | Yes | Mark a course lesson completed |

## Common Setup Issues

1. 401 from protected APIs:
   - Confirm frontend `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` in `frontend/.env.local`.
   - Confirm Google provider and redirect URL are configured in Supabase.

2. Runtime error about SUPABASE_URL or SUPABASE_SERVICE_KEY:
   - Confirm `.env` is present in `interview-app/backend/` or `interview-app/` root.
   - Restart backend after editing `.env`.

3. Questions endpoint returns no data:
   - Run `load_questions_to_supabase.py`.
   - Verify JSON source folder exists at `../output/stage3_company_wise`.


# Interview Practice Platform

A multi-page interview practice web app with **Google OAuth**, **AI-powered hints** (Gemini), and **progress tracking** (Supabase).

## Tech Stack

| Layer      | Technology                          |
| ---------- | ----------------------------------- |
| Backend    | Python, FastAPI                     |
| Frontend   | HTML, Vanilla JS, CSS               |
| Database   | Supabase (PostgreSQL)               |
| Auth       | Supabase Auth (Google OAuth)        |
| AI         | Google Gemini API                   |
| Deploy     | Render (backend), Vercel (frontend) |

---

## Project Structure

```
interview-app/
├── backend/
│   ├── main.py                   # FastAPI entry point
│   ├── routes/
│   │   ├── auth.py               # POST /auth/session
│   │   ├── questions.py          # GET /questions/random, /recommend, /companies, /all
│   │   ├── assistant.py          # POST /assistant/ask
│   │   ├── progress.py           # POST /progress/update, GET /progress/user
│   │   └── revisit.py            # GET /revisit, DELETE /revisit/{id}
│   ├── services/
│   │   ├── supabase_client.py    # Supabase Python client + JWT verification
│   │   ├── gemini_service.py     # Gemini AI prompt builder + API call
│   │   └── questions_service.py  # Question loading from JSON files
│   ├── models/
│   │   └── schemas.py            # Pydantic request/response models
│   └── requirements.txt
├── frontend/
│   ├── login.html                # Google sign-in page
│   ├── dashboard.html            # Main landing after login
│   ├── practice.html             # Interview question trainer
│   ├── revisit.html              # Revisit queue
│   ├── progress.html             # Progress stats
│   ├── css/
│   │   ├── global.css            # Design system + layout
│   │   └── components.css        # UI components
│   └── js/
│       ├── config.js             # API URL + Supabase credentials
│       ├── auth.js               # Supabase auth helper
│       ├── api.js                # Backend API wrapper
│       ├── sidebar.js            # Sidebar navigation
│       ├── dashboard.js          # Dashboard page logic
│       ├── practice.js           # Practice page logic
│       ├── revisit.js            # Revisit page logic
│       └── progress.js           # Progress page logic
├── .env.example
└── README.md
```

---

## 1. Supabase Setup (Required)

### Step 1: Create a Supabase Project

1. Go to [https://supabase.com](https://supabase.com) and sign up / log in.
2. Click **New Project**.
3. Choose an organization, set a project name (e.g., `interview-platform`), set a database password, and choose a region.
4. Wait for the project to be created.

### Step 2: Get API Keys

1. Go to **Settings → API** in your Supabase dashboard.
2. Copy these values:
   - **Project URL** → this is your `SUPABASE_URL`
   - **anon (public) key** → this is your `SUPABASE_ANON_KEY`
   - **service_role key** → this is your `SUPABASE_SERVICE_KEY` (keep this secret!)

### Step 3: Enable Google OAuth

1. Go to **Authentication → Providers** in Supabase dashboard.
2. Enable **Google**.
3. You'll need a Google OAuth Client ID and Secret:
   - Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
   - Create a new project (or use existing)
   - Go to **APIs & Services → Credentials**
   - Click **Create Credentials → OAuth Client ID**
   - Application type: **Web application**
   - Authorized redirect URIs: Add `https://YOUR-SUPABASE-PROJECT.supabase.co/auth/v1/callback`
   - Copy the **Client ID** and **Client Secret**
4. Paste Client ID and Client Secret in the Supabase Google provider settings.
5. Save.

### Step 4: Create Database Tables

Go to **SQL Editor** in Supabase dashboard and run this SQL:

```sql
-- Users table (auto-populated on first login)
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- User progress — one row per user per question
CREATE TABLE user_progress (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  question_id TEXT NOT NULL,
  question_title TEXT,
  company TEXT,
  difficulty TEXT,
  status TEXT CHECK (status IN ('strong', 'good', 'revisit', 'skip')),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, question_id)
);

-- Practice history — one row per attempt
CREATE TABLE practice_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  question_id TEXT NOT NULL,
  question_title TEXT,
  company TEXT,
  difficulty TEXT,
  practiced_at TIMESTAMPTZ DEFAULT now()
);

-- Row Level Security
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE practice_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own profile" ON users FOR SELECT USING (auth.uid() = id);
CREATE POLICY "Users can update own profile" ON users FOR UPDATE USING (auth.uid() = id);
CREATE POLICY "Users can view own progress" ON user_progress FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users can view own history" ON practice_history FOR ALL USING (auth.uid() = user_id);
```

---

## 2. Environment Variables

Copy `.env.example` to `.env` in the `interview-app/` directory:

```bash
cp .env.example .env
```

Fill in your values:

```env
GEMINI_API_KEY=your_gemini_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_KEY=your_service_role_key
GOOGLE_CLIENT_ID=your_google_client_id
```

Also update `frontend/js/config.js` with your Supabase URL and anon key:

```js
const CONFIG = {
  API_BASE_URL: "http://localhost:8000",
  SUPABASE_URL: "https://your-project.supabase.co",
  SUPABASE_ANON_KEY: "your-supabase-anon-key",
};
```

---

## 3. Local Development

### Backend

```bash
cd interview-app/backend

# Create virtual environment (first time)
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.

Test it:
```bash
# Health check
curl http://localhost:8000/health

# Get companies
curl http://localhost:8000/questions/companies

# Get a random question
curl "http://localhost:8000/questions/random?company=Google&difficulty=medium"
```

### Frontend

Just open the HTML files in your browser. For local development, you can use Python's built-in HTTP server:

```bash
cd interview-app/frontend
python -m http.server 3000
```

Then open `http://localhost:3000/login.html` in your browser.

---

## Question Bank Migration (JSON -> Supabase)

To run fully database-native question queries, load the question bank into Supabase once.

1. Run the latest SQL in `supabase_setup.sql` to create:
   - `question_bank_questions`
   - `question_bank_companies`
2. From `interview-app/backend/`, run:

```bash
python load_questions_to_supabase.py --truncate
```

Notes:
- `--truncate` clears old question bank rows before reload.
- The script reads from `../output/stage3_company_wise` and writes to Supabase using `SUPABASE_SERVICE_KEY`.
- Duplicate questions are merged into one canonical row, and the canonical qnum is the minimum qnum among duplicates.
- Source qnums are stored in `question_bank_questions.source_qnums`, and alias mappings are stored in `question_bank_qnum_aliases`.

---

## 4. Deployment

### Backend → Render

1. Push your code to a GitHub repo.
2. Go to [https://render.com](https://render.com) and create a new **Web Service**.
3. Connect your GitHub repo.
4. Settings:
   - **Root directory**: `interview-app/backend`
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables in Render dashboard:
   - `GEMINI_API_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_KEY`
6. Deploy.

### Frontend → Vercel

1. Go to [https://vercel.com](https://vercel.com) and import your GitHub repo.
2. Settings:
   - **Root directory**: `interview-app/frontend`
   - **Framework preset**: Other
   - **Build command**: (leave empty)
   - **Output directory**: `.`
3. Before deploying, update `frontend/js/config.js`:
   - Set `API_BASE_URL` to your Render backend URL (e.g., `https://your-app.onrender.com`)
4. Deploy.

### Update Supabase Redirect URL

After deploying the frontend, go to Supabase **Authentication → URL Configuration** and:
- Add your Vercel URL to **Redirect URLs** (e.g., `https://your-app.vercel.app/dashboard.html`)

---

## 5. Features

- **Google OAuth** — Sign in with Google via Supabase Auth
- **Company-specific questions** — Select from 36 companies (Google, Amazon, Microsoft, etc.)
- **Difficulty filtering** — Easy, Medium, Hard
- **No-repeat random questions** — Each question shown only once per session
- **AI Interview Assistant** — Ask doubts, get hints (not full solutions) via Gemini
- **Progress tracking** — Mark questions as Strong, Good, Revisit, or Skip
- **Revisit queue** — Save questions for later practice
- **Dark/Light theme** — Toggle with sidebar button
- **Responsive design** — Works on mobile with collapsible sidebar
- **Keyboard shortcuts** — `N` for next, `L` for load (on practice page)

---

## 6. API Endpoints

| Method | Endpoint                  | Auth | Description                        |
| ------ | ------------------------- | ---- | ---------------------------------- |
| GET    | `/`                       | No   | Health check                       |
| GET    | `/health`                 | No   | Detailed health check              |
| POST   | `/auth/session`           | No   | Validate token + upsert user       |
| GET    | `/questions/companies`    | No   | List available companies           |
| GET    | `/questions/random`       | No   | Random question by company+diff    |
| GET    | `/questions/recommend`    | No   | Recommended question               |
| GET    | `/questions/all`          | No   | All questions for company+diff     |
| POST   | `/assistant/ask`          | No   | Ask AI assistant a doubt           |
| POST   | `/progress/update`        | Yes  | Mark question status               |
| GET    | `/progress/user`          | Yes  | Get user progress + history        |
| GET    | `/revisit`                | Yes  | Get revisit queue                  |
| DELETE | `/revisit/{question_id}`  | Yes  | Remove from revisit queue          |

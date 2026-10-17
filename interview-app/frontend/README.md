# Interview Assistant — Next.js Frontend

Modern Next.js 16 (App Router) web application for the Interview Practice Platform, featuring interactive practice tools, AI doubt assistant, courses with embedded SQLite practice, and Google OAuth integration.

## Tech Stack & Architecture

- **Framework**: Next.js 16 (App Router) with React 19 & TypeScript
- **Styling**: Tailwind CSS v4 + Custom CSS Theme variables (`@theme` in `globals.css`)
- **Icons**: Lucide React (`lucide-react`)
- **Authentication & SSR**: Supabase Auth (`@supabase/ssr` & `@supabase/supabase-js`)
- **Interactive SQL**: `sql.js` (WebAssembly SQLite in browser for SQL course practice)

## Getting Started

### 1. Environment Configuration

Create a `.env.local` file in the `frontend` root:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
```

### 2. Install Dependencies

```bash
npm install
```

### 3. Run Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Key Feature Components

- `AssistantChat`: Streaming AI assistant chat interface connected to FastAPI backend via Server-Sent Events (SSE).
- `FilterBuilder`: React component for building and persisting custom search & filter queries across question lists.
- `DifficultyRings`: SVG-based visualization component showing solved question stats breakdown (Easy, Medium, Hard).
- `ConsistencyHeatmap`: Practice activity heatmap component showing daily problem-solving trends.
- `SqlEditor`: Client-side interactive SQLite environment powered by `sql.js` for SQL practice courses.

## Build and Deployment

### Production Build

```bash
npm run build
npm run start
```

### Deploying on AWS EC2 (Docker)

1. Push your changes to the `aws-migration` branch on GitHub.
2. SSH into your AWS EC2 instance and pull the latest changes.
3. Configure the environment variables in `interview-app/.env` (`NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `AUTH_REDIRECT_URL=http://16.113.92.222/auth/callback?next=/dashboard`).
4. Build and start the containers:
   ```bash
   docker compose build frontend
   docker compose up -d
   ```


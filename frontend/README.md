# Frontend — Voxera

The manager-facing dashboard for the call-centre radar. It's a **thin,
read-only client**: nothing is transcribed or analysed here — every number,
transcript, and score comes from the FastAPI backend, and every claim in the
UI links back to the exact moment in the call it came from.

## Stack

- **React 19** + **Vite 8** (`@vitejs/plugin-react`, HMR)
- **React Router 7** — client-side routing
- **Tailwind CSS v4** (`@tailwindcss/postcss`) — styling, dark/light theme
- **Recharts** — trend/agent charts
- **Axios** — API client with auth interceptors (`src/api/client.js`)
- **lucide-react** — icons
- **oxlint** — linting

## Prerequisites

- **Node 20.19+ / 22.12+** (Vite 8 requirement)
- **The backend API running on `http://localhost:8000`** — see
  [`../backend/README.md`](../backend/README.md). The dashboard is useless
  without it; there's no mock data.

## Setup

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### Environment

`frontend/.env` sets where the API lives:

```
VITE_API_BASE_URL=http://localhost:8000
```

Change it if the backend runs elsewhere. If unset, the client falls back to
`http://localhost:8000` (`src/api/client.js`).

## Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` | Vite dev server with HMR on `:5173` |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Serve the built `dist/` locally |
| `npm run lint` | Run oxlint |

## Auth

First load redirects to `/login` (`src/pages/Login.jsx`). Sign in with the
manager credentials configured in the backend's `.env`
(`MANAGER_USERNAME` / `MANAGER_PASSWORD_HASH`). On success the JWT is stored
in `localStorage` under `voxera-token` and an Axios request interceptor
attaches it as a bearer token to every call; a response interceptor clears
the token and bounces back to `/login` on any `401`
(`src/api/client.js`, `src/context/AuthContext.jsx`, `RequireAuth` in
`src/App.jsx`). Token lifetime is 8 hours (set by the backend).

## Routes / pages

| Route | Page | Backend |
| --- | --- | --- |
| `/login` | `Login.jsx` | `POST /api/auth/login` |
| `/` | `AttentionQueue.jsx` — calls that need a manager today, filterable | `GET /api/attention`, `/api/intents` |
| `/actions` | `ActionCenter.jsx` — auto-generated task list, status-tracked | `GET/PATCH /api/actions` |
| `/calls/:callId` | `CallDetail.jsx` — transcript, mood timeline, evidence, audio player | `GET /api/calls/{id}`, `/api/calls/{id}/audio` |
| `/customers` | `CustomerList.jsx` — customers with aggregate stats | `GET /api/customers` |
| `/customers/:customerId` | `CustomerDetail.jsx` — one customer's call history | `GET /api/customers/{id}/calls` |
| `/agents` | `AgentsTrends.jsx` — agent performance + intent trends | `GET /api/agents`, `/api/trends` |

Plus two things mounted on every page:

- **Global search** (`components/GlobalSearch.jsx`, in the top bar) — over
  `GET /api/search?q=`, structured + semantic matches.
- **Ask Voxa** (`components/AskWidget.jsx`) — a floating chat widget in the
  bottom-left corner over `POST /api/ask`; answers come back with the
  supporting `call_id`s as chips that deep-link to the call, plus a trace of
  which tools the assistant ran. Open/closed state persists in
  `localStorage`.

## Layout

```
src/
├── main.jsx                 # entry — BrowserRouter → AuthProvider → ThemeProvider → App
├── App.jsx                  # route table + RequireAuth guard + AppShell (Sidebar + AskWidget)
├── index.css                # Tailwind v4 + theme tokens
├── api/client.js            # axios instance, auth interceptors, one function per endpoint
├── context/                 # AuthContext, ThemeContext, AudioPlayerContext
├── hooks/useApi.js          # small fetch-state hook (loading / error / data)
├── pages/                   # one file per route (above)
├── components/              # shared evidence-first primitives:
│                            #   EvidenceChip, ScorePill, MoodChip, MoodTimeline,
│                            #   AudioPlayer, Transcript, Card, PageState, Sidebar,
│                            #   TopBar, GlobalSearch, AskWidget, VoxeraLogo
└── utils/                   # format, mood, scoreBands, attentionReason, avatarColor
```

## Theme

Dark/light toggle in the sidebar, persisted in `localStorage` under
`voxera-theme` (defaults to dark). `index.html` applies the stored theme
before first paint to avoid a flash.

## Notes

- The build currently emits one ~720 kB JS chunk (no code-splitting) — fine
  for an internal dashboard, but the obvious first optimisation if it grows.
- `npm run lint` reports a handful of warnings (unused var, fast-refresh
  export hints, effect-dependency hints); none are errors.

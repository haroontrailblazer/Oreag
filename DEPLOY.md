# Deploying Oreag (frontend + backend separately)

Two independent deploys that talk over HTTPS, both pointing at the same Supabase
project.

```
Browser ──► Vercel (Next.js frontend) ──► Container host (FastAPI backend) ──► Supabase
                     (also calls Supabase Auth directly)
```

## 1. Backend → a container host (Render / Railway / Fly.io / Cloud Run)

Vercel can't run this backend (background-task ingestion + long embed/LLM calls
outlive a serverless request). Deploy it as a normal container instead. A
`backend/Dockerfile` is included.

**Start command** (if not using Docker): `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

**Environment variables:**

| Var | Value |
|---|---|
| `DATABASE_URL` | Supabase session-pooler URI, `postgresql+psycopg://...` |
| `SUPABASE_URL` | `https://<ref>.supabase.co` |
| `SUPABASE_ANON_KEY` | publishable/anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | secret key (Storage access) |
| `APP_ENCRYPTION_KEY` | **required** — Fernet key that encrypts users' own provider keys at rest. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `JWT_MODE` | `jwks` |
| `CORS_ORIGINS` | your Vercel URL, e.g. `https://oreag.vercel.app` (comma-separate multiple) |

After it deploys you get a public URL, e.g. `https://oreag-api.onrender.com`.
Confirm `GET https://oreag-api.onrender.com/healthz` returns `{"status":"ok"}`.

> Provider note: this is **bring-your-own-key (BYOK)** — the server ships no
> shared provider key. Each user adds their own OpenAI / Gemini / Anthropic key
> under **Settings → API keys**, and `/api/models` reports a provider available
> once that user has a key for it. Ollama is localhost-only, so in the cloud it
> is reported unavailable (the wizard greys it out); to use local models, run
> the backend on a host that can reach your Ollama and set `OLLAMA_BASE_URL`.

## 2. Frontend → Vercel

- Import the repo, set **Root Directory = `frontend`**.
- Environment variables:

| Var | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | publishable/anon key |
| `NEXT_PUBLIC_API_BASE_URL` | your backend URL, e.g. `https://oreag-api.onrender.com` |

You get a URL, e.g. `https://oreag.vercel.app`.

## 3. Wire them together (the integration)

1. **CORS** — make sure the backend's `CORS_ORIGINS` contains the exact Vercel
   URL, then redeploy the backend.
2. **API base** — make sure the frontend's `NEXT_PUBLIC_API_BASE_URL` is the
   backend URL (HTTPS — mixed content is blocked), then redeploy the frontend.
3. **Supabase Auth** — Dashboard → Authentication → URL Configuration:
   - Site URL: `https://oreag.vercel.app`
   - Redirect URLs: add `https://oreag.vercel.app/auth/callback`
   (so email-confirmation links return to the deployed app).
4. **Migrations** — already applied to your Supabase project; nothing to do at
   deploy time. For a fresh project, run `supabase/migrations/*.sql` in order.

## Smoke test after deploy

Sign up → confirm email → **Settings → API keys: add your OpenAI (and/or Gemini
/ Anthropic) key** → create a project → upload a PDF → watch it index → ask a
question in the Playground → copy the `curl` from the API tab and run it against
the public `/v1` endpoint.

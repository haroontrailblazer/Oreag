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
| `OPENAI_API_KEY` | **required in the cloud** — Ollama is localhost-only and won't be reachable from a cloud host |
| `JWT_MODE` | `jwks` |
| `CORS_ORIGINS` | your Vercel URL, e.g. `https://oreag.vercel.app` (comma-separate multiple) |

After it deploys you get a public URL, e.g. `https://oreag-api.onrender.com`.
Confirm `GET https://oreag-api.onrender.com/healthz` returns `{"status":"ok"}`.

> Provider note: in the cloud, use **OpenAI**. `/api/models` probes Ollama and
> will report it unavailable, so the wizard automatically greys out local
> options. To use local models you'd have to host Ollama yourself and point
> `OLLAMA_BASE_URL` at it.

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

Sign up → confirm email → create a project (OpenAI models) → upload a PDF →
watch it index → ask a question in the Playground → copy the `curl` from the API
tab and run it against the public `/v1` endpoint.

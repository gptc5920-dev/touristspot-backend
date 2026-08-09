# Travel Osmena Itinerary Builder

Travel Osmena is a Django API and React client for staff-managed tourist destinations and personalized itinerary generation. The planner only uses active, verified destination records from the local database. No destination seed data is shipped.

## Configuration

From the repository root, copy `back-end/.env.example` to `back-end/.env` and set values appropriate for the environment. Django loads that file for local development without overriding variables already supplied by the process. `DJANGO_SECRET_KEY` is required whenever `APP_ENV` is not `development`. In production, set `APP_DEBUG=false`, `SECURE_SSL_REDIRECT=true`, and an appropriate positive `SECURE_HSTS_SECONDS` only after HTTPS is working.

The frontend uses `VITE_API_URL`, which defaults to the Django API proxy at `/api`. To override it, copy `frontend/.env.example` to `frontend/.env`; keep frontend variables separate because Vite exposes `VITE_*` values to browser code.

## Local development

```powershell
cd back-end
python manage.py migrate
python manage.py createsuperuser
```

Start the API and frontend together from one terminal:

```powershell
cd ..\frontend
npm.cmd install
npm.cmd run dev
```

`npm.cmd run dev` starts Django on `127.0.0.1:8000` and Vite on its displayed local URL. To run only one service, use `npm.cmd run dev:api` or `npm.cmd run dev:web`; the frontend-only command requires Django to already be running on port `8000`.

The public planner is available at `/`. The separate React administration workspace is available at `/admin-dashboard/` and renders only after the current session is verified as a staff administrator. Django's `/admin/` route remains reserved for the built-in Django administration site.

Destination cover uploads are stored under Django's `MEDIA_ROOT` (`media/` locally) and served at `/media/` in development. Production deployments should map `MEDIA_ROOT` to persistent storage and serve `MEDIA_URL` through the web server or object-storage provider.

For a different frontend origin, set `CSRF_TRUSTED_ORIGINS` to a comma-separated list of full origins (including scheme and port). Development trusts `http://localhost:5173` and `http://127.0.0.1:5173` by default.

Sign in with the staff account's unique username (recommended) or email, open `/admin-dashboard/`, and add real tourism-office destination records. If legacy accounts share an email, use the username. Only records that are both active and verified are available to the planner.

## API endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health/` | Safe service health summary |
| `GET /api/destinations/` | Active, verified destinations |
| `POST /api/itineraries/generate/` | Validated deterministic itinerary generation |
| `GET/POST /api/itineraries/` | Authenticated user's saved itineraries |
| `POST /api/auth/login/` | CSRF-protected session sign-in |
| `GET/POST/PATCH /api/admin/...` | Staff-only destination administration |

## Known limitations

The hybrid recommender combines destination content, patterns from similar saved itineraries, and the traveler's live trip context. Its collaborative component automatically uses a cold-start fallback until relevant saved itineraries exist. Rankings remain deterministic and explainable; no private traveler identity is returned with collaborative signals.

The scheduler does not call an external LLM, routing, weather, or traffic provider. The map is a Google Maps embed centered on the location supplied by the user. Add external providers only with administrator-managed credentials and server-side validation.

## Verification

```powershell
cd back-end
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
cd ..\frontend
npm.cmd run lint
npm.cmd run build
```

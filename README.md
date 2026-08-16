# Travel Osmena Itinerary Builder

Travel Osmena is a Django API and React client for staff-managed tourist destinations and personalized itinerary generation. The planner only uses active, verified destination records from the local database. No destination seed data is shipped.

## Configuration

From the repository root, copy `back-end/.env.example` to `back-end/.env` and set values appropriate for the environment. Django loads that file for local development without overriding variables already supplied by the process. The application uses MySQL through the `MYSQL_*` settings in that file; Django 5.2 requires MySQL 8.0.11 or newer. `DJANGO_SECRET_KEY` is required whenever `APP_ENV` is not `development`. In production, set `APP_DEBUG=false`, `SECURE_SSL_REDIRECT=true`, and an appropriate positive `SECURE_HSTS_SECONDS` only after HTTPS is working.

The frontend uses `VITE_API_URL`, which defaults to the Django API proxy at `/api`. To override it, copy `frontend/.env.example` to `frontend/.env`; keep frontend variables separate because Vite exposes `VITE_*` values to browser code.

## Nixpacks deployment

Deploy this `back-end` repository as its own Nixpacks application. The tracked
`nixpacks.toml` selects Python 3.13, installs the native MySQL build tooling, and
runs `deploy/start.sh`. Startup waits briefly for MySQL, applies migrations,
collects Django static files, and binds Gunicorn to the platform-provided
`PORT` on all interfaces.

Nixpacks builds the application image; it does not create the database. Attach
a supported MySQL service and configure these production variables in the
hosting dashboard:

```dotenv
APP_ENV=production
APP_DEBUG=false
DJANGO_SECRET_KEY=replace-with-a-long-random-secret
ALLOWED_HOSTS=api.touristspot.site
CSRF_TRUSTED_ORIGINS=https://touristspot.site
CORS_ALLOWED_ORIGINS=https://touristspot.site
CORS_ALLOW_CREDENTIALS=true
CSRF_COOKIE_DOMAIN=.touristspot.site
FRONTEND_URL=https://touristspot.site
MYSQL_DATABASE=tourist
MYSQL_USER=travel_app
MYSQL_PASSWORD=replace-with-the-database-password
MYSQL_HOST=replace-with-the-database-host
MYSQL_PORT=3306
MYSQL_ALLOW_LEGACY_MARIADB=false
SECURE_SSL_REDIRECT=true
SECURE_HSTS_SECONDS=31536000
```

Do not set a fixed production `PORT`; the hosting platform should inject it.
After deployment, `https://api.touristspot.site/` should return the API service
summary and `/api/health/` should report both the service and database as
healthy. Configure the frontend build with
`VITE_API_URL=https://api.touristspot.site/api`. User-uploaded media requires a
persistent volume mounted at the application's `media/` directory, or an
external object-storage backend.

XAMPP's bundled MariaDB 10.4 is below Django 5.2's officially supported
minimum. Local XAMPP development can opt into the project's narrow version-gate
adapter with `MYSQL_ALLOW_LEGACY_MARIADB=true`. Keep this disabled for MySQL 8,
supported MariaDB releases, Docker, and production.

## Local development

Install the Python dependencies, then create a UTF-8 MySQL database and a dedicated local user. Replace the example password here and in `back-end/.env`:

```powershell
cd back-end
python -m pip install -r requirements.txt
mysql -u root -p
```

```sql
CREATE DATABASE tourist CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'travel_app'@'localhost' IDENTIFIED BY 'replace-with-a-strong-database-password';
GRANT ALL PRIVILEGES ON tourist.* TO 'travel_app'@'localhost';
```

Apply the schema and create the first administrator:

```powershell
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

## Migrating an existing SQLite database

The primary database is always MySQL. To preserve records from the former `db.sqlite3`, expose it temporarily through the export-only alias, then import the resulting fixture after running MySQL migrations:

```powershell
cd back-end
$env:SQLITE_MIGRATION_PATH = (Resolve-Path .\db.sqlite3).Path
$env:PYTHONUTF8 = '1'
python manage.py dumpdata --database sqlite_legacy --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --output sqlite-export.json
Remove-Item Env:SQLITE_MIGRATION_PATH
Remove-Item Env:PYTHONUTF8
python manage.py migrate
python manage.py loaddata sqlite-export.json
```

Keep both `db.sqlite3` and `sqlite-export.json` private; both are excluded from Git and Docker build contexts.

Destination cover uploads are stored under Django's `MEDIA_ROOT` (`media/` locally) and served at `/media/` in development. Production deployments should map `MEDIA_ROOT` to persistent storage and serve `MEDIA_URL` through the web server or object-storage provider.

For a different frontend origin, set `CSRF_TRUSTED_ORIGINS` to a comma-separated list of full origins (including scheme and port). Development trusts `http://localhost:5173` and `http://127.0.0.1:5173` by default.

Password reset links use `FRONTEND_URL` and expire after `PASSWORD_RESET_TIMEOUT` seconds (one hour by default). Development prints reset emails in the Django terminal. For production, configure the SMTP `EMAIL_*` values shown in `.env.example` and use `django.core.mail.backends.smtp.EmailBackend`. Checked “Remember me” sessions last `REMEMBER_ME_SECONDS` seconds (14 days by default); unchecked sessions expire when the browser closes.

Sign in with the staff account's unique username (recommended) or email, open `/admin-dashboard/`, and add real tourism-office destination records. If legacy accounts share an email, use the username. Only records that are both active and verified are available to the planner.

## API endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health/` | Safe service health summary |
| `GET /api/destinations/` | Active, verified destinations |
| `POST /api/itineraries/generate/` | Validated deterministic itinerary generation |
| `GET/POST /api/itineraries/` | Authenticated user's saved itineraries |
| `POST /api/auth/login/` | CSRF-protected session sign-in |
| `POST /api/auth/password-reset/` | Request a password reset email |
| `POST /api/auth/password-reset/confirm/` | Set a password using a one-time reset token |
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

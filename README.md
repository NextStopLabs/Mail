# Mail

Webmail client for `webmail.nextstoplabs.org`, backed by the existing
Modoboa / Postfix / Dovecot stack on `mail.nextstoplabs.org`. The browser
talks to a Next.js frontend and a Django API; only the backend touches
IMAP/SMTP.

```
Browser → Next.js → Django REST → IMAP (993 SSL / 143 STARTTLS)
                               → SMTP (587 STARTTLS)
```

## Stack

- Frontend: Next.js 14, React 18, TypeScript, Tailwind CSS
- Backend: Django 5, DRF, `imaplib` / `smtplib`, `nh3`/`bleach`, Postgres, Redis, Gunicorn
- Infra: Docker Compose, Nginx

## Run it

```bash
cp .env.example .env   # set secrets and hosts
docker compose up --build
```

- Web UI: http://localhost:8080 (Nginx) or http://localhost:3000 (Next.js directly)
- API health: http://localhost:8080/api/health/

Without Docker:

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DJANGO_DEBUG=True python manage.py migrate
DJANGO_DEBUG=True python manage.py runserver 8000

# Frontend
cd frontend
npm install
npm run dev   # http://localhost:3000, proxies /api to Django
```

## Configuration

Everything comes from the environment (see `.env.example`):

| Variable | Purpose | Default |
|---|---|---|
| `DJANGO_SECRET_KEY` | Sessions, credential encryption | — (required) |
| `DJANGO_DEBUG` | Dev mode (locmem cache, DB sessions) | `False` |
| `DJANGO_ALLOWED_HOSTS` | Allowed hosts | `localhost,127.0.0.1` |
| `DATABASE_URL` | Postgres connection string | sqlite (dev) |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `MAIL_IMAP_HOST/PORT/SECURITY` | IMAP server | `mail.nextstoplabs.org:993 SSL` |
| `MAIL_SMTP_HOST/PORT/SECURITY` | SMTP server | `mail.nextstoplabs.org:587 STARTTLS` |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | Secure cookies | `False` (set `True` in prod) |
| `LOGIN_RATE_LIMIT` | Login attempts allowed | `10/minute` |
| `NEXT_PUBLIC_API_URL` | API base baked into the frontend build | `/api` |

Login uses mailbox credentials verified against IMAP. Passwords are
Fernet-encrypted (key derived from `DJANGO_SECRET_KEY`) and kept in the
server-side session only — never sent to the frontend or logged.

## Deploy

Build locally:

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

Or use the prebuilt images CI publishes to GHCR on every push to `main`
(`ghcr.io/nextstoplabs/mail-backend`, `.../mail-frontend`):

```bash
docker compose -f docker-compose.images.yml pull
docker compose -f docker-compose.images.yml up -d
# Pin a specific build: IMAGE_TAG=<short-sha> docker compose -f docker-compose.images.yml up -d
```

Nginx terminates TLS (certs from `/etc/letsencrypt`, see
`nginx/nginx.prod.conf`) and proxies to the frontend and backend.
The mail server itself is untouched.

## API

Session cookie + `X-CSRFToken` header required, except login/CSRF:

```
POST /api/auth/login/            {email, password}
POST /api/auth/logout/
GET  /api/auth/me/
GET  /api/auth/csrf/
GET  /api/mailboxes/
GET  /api/mailboxes/<mailbox>/messages/?page=&page_size=&q=
GET  /api/messages/<mailbox>/<uid>/?thread=1
POST /api/messages/<mailbox>/<uid>/read/    {read}
POST /api/messages/<mailbox>/<uid>/flag/    {flagged}
POST /api/messages/<mailbox>/<uid>/move/    {dest}
POST /api/messages/<mailbox>/<uid>/copy/    {dest}
POST /api/messages/<mailbox>/<uid>/delete/
POST /api/messages/bulk/                    {mailbox, uids, action, value, dest}
GET  /api/messages/<mailbox>/<uid>/attachments/?filename=&part=
GET  /api/search/?mailbox=&q=&from=&subject=&unread=&flagged=
POST /api/send/        {to, cc, bcc, subject, text, html, attachments, draftUid?}
POST /api/drafts/      save/update a draft, or {action: "cleanup", keep:} to prune
DELETE /api/drafts/    {draftUid, mailbox}
GET  /api/health/
```

## Tests

```bash
cd backend
DJANGO_DEBUG=True DJANGO_SECRET_KEY=test-key python manage.py test
```

All IMAP/SMTP tests are mocked — no live mail server needed. CI
(`.github/workflows/ci.yml`) runs these plus the frontend typecheck and
build, then publishes the Docker images.

## Notes

- Mailbox counts are cached 60s per user and invalidated on every mutation.
- Draft autosave replaces one IMAP message per compose session; sending or
  discarding deletes it. Old duplicate piles can be pruned from the Drafts
  folder ("Keep newest 10") or via the cleanup action above.
- Attachments are capped at 25 MB per file (30 MB request body).
- HTML mail is sanitized server-side (`nh3`, `bleach` fallback).

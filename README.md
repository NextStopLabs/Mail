# NextStop Webmail — Modern Webmail for webmail.nextstoplabs.org

A polished, modern webmail client for the existing Modoboa / Postfix / Dovecot stack at `mail.nextstoplabs.org`. No JMAP, no mailbox migration — just a SaaS-grade UI on top of IMAP (993 SSL / 143 STARTTLS) and SMTP (587 STARTTLS).

**Architecture:** Browser → Next.js (React + TypeScript) → Django REST (Python) → IMAP/SMTP → Dovecot/Postfix. Browser never touches IMAP/SMTP.

---

## Features

- **Auth** via existing mailbox credentials (IMAP verify), encrypted session cookies (HTTP-only, SameSite=Lax, Secure in prod), CSRF, rate-limited login, no password logging.
- **IMAP layer** clean `MailService` abstraction: connection reuse, reconnection, timeout handling, per-user isolation, UID-based pagination, graceful failures.
- **Folders** discovered via `LIST`, roles auto-detected (Inbox/Sent/Drafts/Trash/Spam/Archive/Custom/Nested), unread counts via `STATUS`.
- **Inbox** sender avatar, subject, snippet, date, read/star/attachment states, subtle unread distinction.
- **Reader** sanitized HTML via `nh3`/`bleach`, sandbox `iframe`, plain/multipart handling, inline CID, attachment streaming (no RAM blowup), headers view.
- **Compose** To/Cc/Bcc, subject, rich text + plain fallback, attachments, draft autosave (debounced, deduped), Reply/ReplyAll/Forward, SMTP via `mail.nextstoplabs.org:587` STARTTLS.
- **Actions** mark read/unread, star, archive, move, copy, delete, bulk actions — all reflected in IMAP.
- **Search** IMAP `SEARCH TEXT/FROM/SUBJECT` server-side, no full mailbox download.
- **Threading** Message-ID / In-Reply-To / References + subject fallback, grouped threads.
- **Pagination** UID-based, page size 50, efficient FETCH.
- **Caching** folder list/counts via Redis (locmem in dev), invalidated on mutations.
- **Security** CSP, XSS sanitization, MIME validation, filename sanitization, permission checks, security headers, no credential exposure.
- **UI** clean typography, subtle borders, rounded components, dark/light/system tokens, responsive (desktop multi-column → mobile single-pane drawer), keyboard shortcuts (`c,r,a,f,e,#,j,k,?`), shortcuts help.
- **Deployment** Docker Compose (Django + Next.js + Postgres + Redis + Nginx), env-var config, `.env.example`.

---

## Quick Start

```bash
cp .env.example .env   # fill DJANGO_SECRET_KEY, DB, etc.
docker compose up --build
# Frontend: http://localhost:8080  (nginx)  or http://localhost:3000
# API:      http://localhost:8080/api/health/
```

Development without Docker:

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

---

## Configuration

All via env (see `.env.example`):

```
MAIL_IMAP_HOST=mail.nextstoplabs.org
MAIL_IMAP_PORT=993
MAIL_IMAP_SECURITY=SSL
MAIL_SMTP_HOST=mail.nextstoplabs.org
MAIL_SMTP_PORT=587
MAIL_SMTP_SECURITY=STARTTLS
DJANGO_SECRET_KEY=...
DATABASE_URL=postgres://webmail:webmail@db:5432/webmail
REDIS_URL=redis://redis:6379/0
NEXT_PUBLIC_API_URL=https://webmail.nextstoplabs.org/api
```

---

## API

```
POST   /api/auth/login/          {email, password}
POST   /api/auth/logout/
GET    /api/auth/me/
GET    /api/auth/csrf/
GET    /api/mailboxes/
GET    /api/mailboxes/<mailbox>/messages/?page=1&page_size=50&q=&filter=unread|flagged
GET    /api/messages/<mailbox>/<uid>/
POST   /api/messages/<mailbox>/<uid>/read/   {read: bool}
POST   /api/messages/<mailbox>/<uid>/flag/   {flagged: bool}
POST   /api/messages/<mailbox>/<uid>/move/   {dest}
POST   /api/messages/<mailbox>/<uid>/delete/
GET    /api/messages/<mailbox>/<uid>/attachments/?filename=&part=
POST   /api/messages/bulk/               {mailbox, uids, action, value, dest}
GET    /api/search/?mailbox=INBOX&q=&from=&subject=&unread=&flagged=
POST   /api/send/           {to, cc, bcc, subject, text, html, attachments}
POST   /api/drafts/         {to, cc, bcc, subject, text, html, mailbox, draftUid}
GET    /api/health/
```

All except `/auth/login/` and `/auth/csrf/` require session cookie + CSRF header (`X-CSRFToken`).

---

## Security Notes

- Credentials encrypted with Fernet (derived from `DJANGO_SECRET_KEY`) and stored in server-side session (DB/cache), never sent to frontend, never logged.
- HTML email sanitized via `nh3`; `iframe[sandbox]`, `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`.
- Rate limiting on login (100/min), secure cookies, CSRF, HSTS in prod.

---

## Testing

```bash
cd backend
DJANGO_DEBUG=True python -m django test --settings=config.settings --verbosity=2
# Or via unittest discover:
DJANGO_DEBUG=True python -c "import django; django.setup(); import unittest; loader=unittest.TestLoader(); suite=loader.discover('apps', pattern='test_*.py'); runner=unittest.TextTestRunner(verbosity=2); runner.run(suite)"
```

Covers: auth (success/fail/expired/logout), IMAP (folders, listing, retrieval, flags, move/delete, search, connection failure), SMTP, MIME (plain/html/multipart, attachments, inline, UTF-8, malformed), security (XSS, filename traversal, cross-user, CSRF).

---

## Production

```bash
docker compose -f docker-compose.prod.yml up --build -d
# Nginx reverse-proxies webmail.nextstoplabs.org → frontend:3000 + backend:8000
# Postgres + Redis persist in volumes pgdata/redisdata
# Obtain certs: certbot or mount /etc/letsencrypt
```

The existing Modoboa/Postfix/Dovecot on `mail.nextstoplabs.org` remains untouched. New app serves `webmail.nextstoplabs.org` via Nginx.

---

## Tech Stack

- **Backend:** Django 5, DRF, `imaplib` + `email` (std), `smtplib`, `nh3`/`bleach`, `cryptography`, `django-redis`, PostgreSQL, Gunicorn, WhiteNoise
- **Frontend:** Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, `lucide-react`, `date-fns`
- **Infra:** Docker, Nginx, Redis, Postgres

---

## Milestones Implemented

1. Django + Next.js + Auth + IMAP + Inbox + Reader ✓
2. Folders + Read/Flag/Delete/Move ✓
3. Compose + SMTP + Reply/Forward + Attachments ✓
4. Drafts + Search + Threading ✓
5. Mobile + Dark mode + Shortcuts + Preferences ✓
6. Security + Rate limiting + Error handling + Logging + Tests + Docker ✓

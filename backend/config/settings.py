import os
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-key-change-in-production-please-rotate")
DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() in ("true", "1", "yes")
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
if DEBUG and "testserver" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("testserver")
if "*" not in ALLOWED_HOSTS and "testserver" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("testserver")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "django_filters",
    "apps.accounts",
    "apps.mail",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///" + str(BASE_DIR / "db.sqlite3"))
DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}

# Cache / Redis
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache" if not DEBUG else "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"} if not DEBUG else {},
    }
}
# Fallback to locmem if redis not available in dev
if DEBUG:
    try:
        import django_redis  # noqa
    except Exception:
        CACHES["default"] = {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}

# Session
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db" if not DEBUG else "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", "1209600"))
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "False").lower() in ("true", "1")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", "False").lower() in ("true", "1")
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "https://webmail.nextstoplabs.org,http://localhost:3000,http://localhost:8080").split(",") if o
]

# CORS
CORS_ALLOWED_ORIGINS = [o for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8080").split(",") if o]
CORS_ALLOW_CREDENTIALS = True

# Security
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if not DEBUG else None
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.SessionAuthenticationExemptCSRFForAPI",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle", "rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "1000/hour", "anon": "100/minute", "login": "10/minute"},
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Mail infra
MAIL_IMAP_HOST = os.environ.get("MAIL_IMAP_HOST", "mail.nextstoplabs.org")
MAIL_IMAP_PORT = int(os.environ.get("MAIL_IMAP_PORT", "993"))
MAIL_IMAP_SECURITY = os.environ.get("MAIL_IMAP_SECURITY", "SSL")  # SSL or STARTTLS
MAIL_SMTP_HOST = os.environ.get("MAIL_SMTP_HOST", "mail.nextstoplabs.org")
MAIL_SMTP_PORT = int(os.environ.get("MAIL_SMTP_PORT", "587"))
MAIL_SMTP_SECURITY = os.environ.get("MAIL_SMTP_SECURITY", "STARTTLS")

# Logging - never log passwords
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {module} {message}", "style": "{"},
    },
    "filters": {
        "hide_password": {"()": "apps.accounts.filters.HidePasswordFilter"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose", "filters": ["hide_password"]},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "mail": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "auth": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Auth: we use session + custom IMAP verification, no local user DB password
AUTH_USER_MODEL = "accounts.WebmailUser"

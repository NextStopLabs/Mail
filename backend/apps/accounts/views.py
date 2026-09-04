import logging
import os
from django.contrib.auth import get_user_model, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from django.conf import settings
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import AnonRateThrottle
from apps.accounts.crypto import encrypt_password
from apps.mail.services.imap_client import verify_credentials, IMAPAuthError

logger = logging.getLogger("auth")

class LoginThrottle(AnonRateThrottle):
    # Brute-force protection. Overridable via env (see .env.example) so CI/tests
    # can raise it without touching code. Settings THROTTLE_RATES login is fallback.
    rate = os.environ.get("LOGIN_RATE_LIMIT", "10/minute")
    scope = "login"

User = get_user_model()

@method_decorator(ensure_csrf_cookie, name="dispatch")
class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginThrottle]
    authentication_classes = []  # no auth needed

    def post(self, request):
        email = (request.data.get("email") or request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        if not email or not password:
            return Response({"detail": "Email and password required."}, status=status.HTTP_400_BAD_REQUEST)

        # Verify against IMAP - never log password
        try:
            verify_credentials(email, password)
        except IMAPAuthError as e:
            logger.info("auth failure for %s: %s", email, str(e))
            return Response({"detail": "Invalid email or password."}, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            logger.error("IMAP verification error for %s: %s", email, type(e).__name__)
            return Response({"detail": "Mail server unavailable. Please try again later."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Get or create local user (no password stored)
        user, created = User.objects.get_or_create(email=email, defaults={"is_active": True})
        if not user.is_active:
            return Response({"detail": "Account disabled."}, status=status.HTTP_403_FORBIDDEN)

        login(request, user)
        # Store encrypted credentials in session - isolated per user, never exposed to frontend
        request.session["mail_creds"] = encrypt_password(password)
        request.session["mail_email"] = email
        # Ensure session saved
        request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        logger.info("auth success for %s", email)
        return Response({"email": user.email, "theme": user.theme, "signature": user.signature})

    def get(self, request):
        # Provide CSRF cookie
        return Response({"detail": "CSRF cookie set"})


class LogoutView(APIView):
    permission_classes = [permissions.AllowAny]
    def post(self, request):
        email = request.session.get("mail_email", "unknown")
        logout(request)
        logger.info("logout for %s", email)
        return Response({"detail": "Logged out"})


class MeView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"authenticated": False}, status=status.HTTP_401_UNAUTHORIZED)
        return Response({
            "authenticated": True,
            "email": request.user.email,
            "theme": request.user.theme,
            "density": request.user.density,
            "signature": request.user.signature,
        })


class PreferencesView(APIView):
    def patch(self, request):
        user = request.user
        for field in ("theme", "density", "signature"):
            if field in request.data:
                setattr(user, field, request.data[field])
        allowed_themes = ("light", "dark", "system")
        if user.theme not in allowed_themes:
            return Response({"detail": "Invalid theme"}, status=400)
        user.save(update_fields=["theme", "density", "signature"])
        return Response({"theme": user.theme, "density": user.density, "signature": user.signature})

    def get(self, request):
        user = request.user
        return Response({"theme": user.theme, "density": user.density, "signature": user.signature})

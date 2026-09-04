from rest_framework.authentication import SessionAuthentication
from django.contrib.auth import get_user_model

class SessionAuthenticationExemptCSRFForAPI(SessionAuthentication):
    """
    SessionAuthentication that enforces CSRF for unsafe methods,
    but allows frontend to fetch CSRF token via cookie.
    We keep CSRF protection; DRF's SessionAuthentication already checks CSRF.
    This subclass just provides clearer error messages.
    """
    def enforce_csrf(self, request):
        # Use default CSRF check
        return super().enforce_csrf(request)

def get_user_from_session(request):
    User = get_user_model()
    user_id = request.session.get("_auth_user_id")
    if not user_id:
        return None
    try:
        return User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return None

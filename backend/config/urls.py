from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.db import connection

def health(request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        return JsonResponse({"status": "ok", "db": "ok"})
    except Exception:
        return JsonResponse({"status": "degraded", "db": "error"}, status=503)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.mail.urls")),
]

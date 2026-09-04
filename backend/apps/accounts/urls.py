from django.urls import path
from .views import LoginView, LogoutView, MeView, PreferencesView

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("preferences/", PreferencesView.as_view(), name="preferences"),
    path("csrf/", LoginView.as_view(), name="csrf"),
]

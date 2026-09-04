from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.utils import timezone

class WebmailUserManager(BaseUserManager):
    def create_user(self, email, **extra_fields):
        if not email:
            raise ValueError("Email required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.model(email=self.normalize_email(email), **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

class WebmailUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    # Preferences stored here, NOT passwords
    theme = models.CharField(max_length=20, default="system")  # light, dark, system
    density = models.CharField(max_length=20, default="comfortable")
    signature = models.TextField(blank=True, default="")
    # No password field used for mail auth; AbstractBaseUser password only for admin
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = WebmailUserManager()

    def __str__(self):
        return self.email

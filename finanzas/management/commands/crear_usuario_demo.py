import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea/actualiza el usuario de acceso a partir de DEMO_USER y DEMO_PASSWORD."

    def handle(self, *args, **opts):
        usuario = os.environ.get("DEMO_USER")
        password = os.environ.get("DEMO_PASSWORD")
        if not usuario or not password:
            self.stdout.write(self.style.WARNING("DEMO_USER/DEMO_PASSWORD no definidos; se omite."))
            return
        User = get_user_model()
        user, creado = User.objects.get_or_create(username=usuario)
        user.is_staff = user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Usuario '{usuario}' {'creado' if creado else 'actualizado'}."))

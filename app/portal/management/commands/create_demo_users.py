import os

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the demo users: 'demo' (load generator) and 'ops-admin' (staff; fault injection)."

    def handle(self, *args, **opts):
        if not (settings.DEBUG or settings.FAULTS_ENABLED):
            raise CommandError("Refusing to create demo users unless DEBUG or FAULTS_ENABLED is on.")
        for name, env, default, staff in [
            ("demo", "DEMO_USER_PASSWORD", "demo-pass", False),
            ("ops-admin", "DEMO_OPS_PASSWORD", "ops-pass", True),
        ]:
            user, _ = User.objects.get_or_create(username=name)
            user.is_staff = staff
            user.set_password(os.environ.get(env, default))
            user.save()
            self.stdout.write(f"user '{name}' ready (staff={staff})")

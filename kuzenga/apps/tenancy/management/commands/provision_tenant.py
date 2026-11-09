from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tenancy.models import Membership, Plan, Role, Tenant
from apps.tenancy.services import activate_plan


class Command(BaseCommand):
    help = "Provision a school tenant with an owner account and a plan."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--slug", required=True)
        parser.add_argument("--owner-email", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--plan", default="standard")
        parser.add_argument("--trial-days", type=int, default=None)

    @transaction.atomic
    def handle(self, *args, **o):
        try:
            plan = Plan.objects.get(code=o["plan"])
        except Plan.DoesNotExist as exc:
            raise CommandError("Plan not found. Run: python manage.py seed_catalog") from exc
        tenant = Tenant.objects.create(name=o["name"], slug=o["slug"], status=Tenant.Status.ACTIVE)
        User = get_user_model()
        user = User.objects.filter(
            email=o["owner_email"].lower()
        ).first() or User.objects.create_user(o["owner_email"], o["password"])
        Membership.objects.create(user=user, tenant=tenant, role=Role.OWNER)
        activate_plan(tenant, plan, trial_days=o["trial_days"])
        self.stdout.write(
            self.style.SUCCESS(f"Provisioned {tenant.name} ({plan.code}) for {user.email}")
        )

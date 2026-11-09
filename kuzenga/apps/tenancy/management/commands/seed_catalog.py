from django.core.management.base import BaseCommand

from apps.tenancy.models import Module, Plan, PlanModule

MODULES = [
    ("academics", "Academic structure", "Years, terms, grades, classes and subjects.", []),
    ("students", "Students & guardians", "Learner and guardian records, enrolment.", ["academics"]),
    ("attendance", "Attendance", "Daily class registers.", ["students", "academics"]),
    (
        "assessments",
        "Assessments & results",
        "Marks, grading and report cards.",
        ["students", "academics"],
    ),
    ("finance", "Fees & finance", "Fee schedules, invoices, payments, receipts.", ["students"]),
    ("communications", "Communication", "Announcements, email and SMS.", ["students"]),
]
PLANS = [
    ("starter", "Starter", ["academics", "students"]),
    ("standard", "Standard", ["academics", "students", "attendance", "assessments"]),
    (
        "professional",
        "Professional",
        ["academics", "students", "attendance", "assessments", "finance", "communications"],
    ),
]


class Command(BaseCommand):
    help = "Create/update the module catalogue and default plans (idempotent)."

    def handle(self, *args, **options):
        for code, name, desc, _deps in MODULES:
            Module.objects.update_or_create(code=code, defaults={"name": name, "description": desc})
        for code, _n, _d, deps in MODULES:
            Module.objects.get(code=code).depends_on.set(Module.objects.filter(code__in=deps))
        for code, name, module_codes in PLANS:
            plan, _ = Plan.objects.update_or_create(code=code, defaults={"name": name})
            for m in module_codes:
                PlanModule.objects.get_or_create(plan=plan, module_id=m)
        self.stdout.write(self.style.SUCCESS("Catalogue seeded."))

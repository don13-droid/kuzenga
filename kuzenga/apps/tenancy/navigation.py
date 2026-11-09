"""Sidebar is generated from entitlements + permissions (never a hard-coded list per school)."""

NAV_ITEMS = [
    {"label": "Dashboard", "url": "dashboard", "module": None, "permission": None},
    {"label": "Users & staff", "url": "tenancy:users", "module": None, "permission": "users.view"},
    {
        "label": "Students",
        "url": "students:list",
        "module": "students",
        "permission": "students.view",
    },
    {
        "label": "Admissions",
        "url": "admissions:dashboard",
        "module": "students",
        "permission": "admissions.view",
    },
    {
        "label": "Academics",
        "url": "academics:overview",
        "module": "academics",
        "permission": "academics.view",
    },
    {"label": "Years & terms", "url": "academics:years", "module": "academics", "permission": "academics.view"},
    {"label": "Classes & streams", "url": "academics:classes", "module": "academics", "permission": "academics.view"},
    {"label": "Subjects", "url": "academics:subjects", "module": "academics", "permission": "academics.view"},
    {"label": "Teacher allocations", "url": "academics:allocations", "module": "academics", "permission": "academics.view"},
    {"label": "Student progression", "url": "academics:progression", "module": "academics", "permission": "academics.manage"},
    {
        "label": "Attendance",
        "url": "attendance:today",
        "module": "attendance",
        "permission": "attendance.view",
    },
]

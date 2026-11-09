"""Permission registry. Deny by default; extend per role as modules arrive."""

from .models import Role

ALL = "*"

ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.OWNER: {ALL},
    Role.ADMIN: {
        "academics.view",
        "academics.manage",
        "students.view",
        "students.manage",
        "admissions.view",
        "admissions.manage",
        "admissions.review",
        "admissions.enrol",
        "attendance.view",
        "attendance.take_register",
        "users.view",
        "users.manage",
    },
    Role.TEACHER: {
        "academics.view",
        "students.view",
        "attendance.view",
        "attendance.take_register",
    },
    Role.HOD: {"academics.view", "students.view", "attendance.view", "attendance.take_register"},
    Role.BURSAR: {"students.view"},
    Role.STAFF: set(),
    Role.GUARDIAN: set(),
    Role.STUDENT: set(),
}


def has_permission(membership, permission: str) -> bool:
    if membership is None or membership.status != "active":
        return False
    granted = ROLE_PERMISSIONS.get(membership.role, set())
    return ALL in granted or permission in granted

from django.db import DatabaseError, connections
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    """Report service health, including database connectivity."""
    try:
        connections["default"].ensure_connection()
    except DatabaseError:
        return Response({"status": "unhealthy", "database": "unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"status": "ok", "database": "ok"}, status=status.HTTP_200_OK)

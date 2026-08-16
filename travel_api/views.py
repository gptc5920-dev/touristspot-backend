import logging

from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_safe

from .openapi import build_openapi_schema, swagger_ui_html


logger = logging.getLogger('itineraries')


@require_safe
def api_root(request):
    return JsonResponse({
        'service': 'Travel Osmena API',
        'status': 'online',
        'health': '/api/health/',
    })


@require_safe
def openapi_schema(request):
    server_url = request.build_absolute_uri('/').rstrip('/')
    return JsonResponse(build_openapi_schema(server_url))


@require_safe
def api_docs(request):
    response = HttpResponse(
        swagger_ui_html(reverse('api-schema')),
        content_type='text/html; charset=utf-8',
    )
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    response.headers['Content-Security-Policy'] = (
        "default-src 'none'; "
        "connect-src 'self'; "
        "img-src 'self' data: https:; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com"
    )
    return response


def csrf_failure(request, reason=''):
    logger.warning('csrf_rejected path=%s reason=%s', request.path, reason)
    return JsonResponse({
        'success': False,
        'message': 'Your session verification expired. Please retry the request.',
        'errors': {'csrf': ['Refresh the page if this message persists.']},
    }, status=403)

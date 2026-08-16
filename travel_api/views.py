import logging

from django.http import JsonResponse
from django.views.decorators.http import require_safe


logger = logging.getLogger('itineraries')


@require_safe
def api_root(request):
    return JsonResponse({
        'service': 'Travel Osmena API',
        'status': 'online',
        'health': '/api/health/',
    })


def csrf_failure(request, reason=''):
    logger.warning('csrf_rejected path=%s reason=%s', request.path, reason)
    return JsonResponse({
        'success': False,
        'message': 'Your session verification expired. Please retry the request.',
        'errors': {'csrf': ['Refresh the page if this message persists.']},
    }, status=403)

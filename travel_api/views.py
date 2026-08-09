import logging

from django.http import JsonResponse


logger = logging.getLogger('itineraries')


def csrf_failure(request, reason=''):
    logger.warning('csrf_rejected path=%s reason=%s', request.path, reason)
    return JsonResponse({
        'success': False,
        'message': 'Your session verification expired. Please retry the request.',
        'errors': {'csrf': ['Refresh the page if this message persists.']},
    }, status=403)

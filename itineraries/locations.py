"""Cached Philippine geographic lookups backed by PSGC Cloud v2."""

import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET


SOURCE = 'https://psgc.cloud/api/v2'
CODE_PATTERN = re.compile(r'[0-9]{10}')
logger = logging.getLogger('itineraries')


def _lookup(request, path):
    key = f'psgc-v2:{path}'
    rows = cache.get(key)
    if rows is None:
        try:
            upstream = Request(f'{SOURCE}/{path}', headers={
                'Accept': 'application/json', 'User-Agent': 'TravelOsmena/1.0',
            })
            with urlopen(upstream, timeout=10) as response:
                payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise ValueError('Geographic response exceeds the size limit.')
            body = json.loads(payload)
            rows = body.get('data') if isinstance(body, dict) else None
            if not isinstance(rows, list) or any(
                not isinstance(row, dict)
                or not isinstance(row.get('code'), str)
                or not CODE_PATTERN.fullmatch(row['code'])
                or not isinstance(row.get('name'), str)
                for row in rows
            ):
                raise ValueError('Invalid geographic response.')
            rows = sorted(rows, key=lambda row: row['name'].casefold())
            cache.set(key, rows, timeout=86400)
        except HTTPError as error:
            if error.code == 404:
                return JsonResponse({'error': 'Location code not found.'}, status=404)
            logger.warning('location_provider_http_error path=%s status=%s', path, error.code)
            return JsonResponse({'error': 'Location data is temporarily unavailable. Please try again.'}, status=503)
        except (URLError, OSError, ValueError):
            logger.exception('location_provider_failure path=%s', path)
            return JsonResponse({'error': 'Location data is temporarily unavailable. Please try again.'}, status=503)

    query = request.GET.get('q', '').strip().casefold()
    if query:
        rows = [row for row in rows if query in row['name'].casefold()]
    return JsonResponse({'data': rows, 'count': len(rows), 'source': SOURCE})


@require_GET
def provinces(request):
    return _lookup(request, 'provinces')


@require_GET
def municipalities(request):
    code = request.GET.get('province_code', '').strip()
    if code and not CODE_PATTERN.fullmatch(code):
        return JsonResponse({'error': 'province_code must be a 10-digit PSGC code.'}, status=400)
    path = f'provinces/{code}/cities-municipalities' if code else 'cities-municipalities'
    return _lookup(request, path)


@require_GET
def barangays(request):
    code = request.GET.get('municipality_code', '').strip()
    if not CODE_PATTERN.fullmatch(code):
        return JsonResponse({'error': 'A 10-digit municipality_code is required (city or municipality).'}, status=400)
    return _lookup(request, f'cities-municipalities/{code}/barangays')

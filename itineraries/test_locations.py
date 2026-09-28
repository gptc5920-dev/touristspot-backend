import io
import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.core.cache import cache
from django.test import SimpleTestCase


class LocationApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def response(self, rows):
        return io.BytesIO(json.dumps({'data': rows}).encode())

    @patch('itineraries.locations.urlopen')
    def test_province_search_uses_cached_complete_list(self, fetch):
        fetch.return_value = self.response([
            {'code': '0907200000', 'name': 'Zamboanga del Norte'},
            {'code': '0102800000', 'name': 'Ilocos Norte'},
        ])
        result = self.client.get('/api/locations/provinces/?q=zamboanga')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data'][0]['code'], '0907200000')
        result = self.client.get('/api/locations/provinces/')
        self.assertEqual(result.json()['count'], 2)
        self.assertEqual(result.json()['data'][0]['name'], 'Ilocos Norte')
        fetch.assert_called_once()

    @patch('itineraries.locations.urlopen')
    def test_municipalities_are_scoped_to_province(self, fetch):
        fetch.return_value = self.response([])
        result = self.client.get('/api/locations/municipalities/?province_code=0907200000')
        self.assertEqual(result.status_code, 200)
        self.assertTrue(fetch.call_args.args[0].full_url.endswith('/provinces/0907200000/cities-municipalities'))

    @patch('itineraries.locations.urlopen')
    def test_barangays_require_parent_and_use_its_code(self, fetch):
        self.assertEqual(self.client.get('/api/locations/barangays/').status_code, 400)
        self.assertEqual(self.client.get('/api/locations/municipalities/?province_code=../bad').status_code, 400)
        fetch.assert_not_called()
        fetch.return_value = self.response([{'code': '0907220001', 'name': 'Balatakan'}])
        result = self.client.get('/api/locations/barangays/?municipality_code=0907220000')
        self.assertEqual(result.json()['count'], 1)
        self.assertTrue(fetch.call_args.args[0].full_url.endswith('/cities-municipalities/0907220000/barangays'))

    @patch('itineraries.locations.urlopen', side_effect=URLError('offline'))
    def test_provider_outage_returns_json(self, fetch):
        with self.assertLogs('itineraries', level='ERROR'):
            result = self.client.get('/api/locations/provinces/')
        self.assertEqual(result.status_code, 503)
        self.assertIn('error', result.json())

    @patch('itineraries.locations.urlopen')
    def test_invalid_upstream_data_is_not_cached(self, fetch):
        fetch.return_value = io.BytesIO(b'<html>Proxy error</html>')
        with self.assertLogs('itineraries', level='ERROR'):
            self.assertEqual(self.client.get('/api/locations/provinces/').status_code, 503)
        fetch.return_value = self.response([])
        self.assertEqual(self.client.get('/api/locations/provinces/').status_code, 200)
        self.assertEqual(fetch.call_count, 2)

    @patch('itineraries.locations.urlopen', side_effect=HTTPError('https://psgc.cloud', 404, 'Not found', {}, None))
    def test_unknown_parent_returns_not_found(self, fetch):
        result = self.client.get('/api/locations/barangays/?municipality_code=0000000000')
        self.assertEqual(result.status_code, 404)
        self.assertIn('error', result.json())

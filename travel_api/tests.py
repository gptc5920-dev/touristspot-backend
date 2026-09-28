import os
import runpy
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import StorageHandler
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, override_settings

from itineraries.urls import urlpatterns as itinerary_urlpatterns

from .views import api_root


class DatabaseDriverTests(SimpleTestCase):
    def test_mysql_backend_uses_pymysql(self):
        self.assertEqual(connection.Database.__name__, 'pymysql')


class ProductionMediaStorageTests(SimpleTestCase):
    def test_production_configuration_can_store_uploaded_files(self):
        with patch.dict(os.environ, {'APP_DEBUG': 'false'}):
            production = runpy.run_path(str(Path(__file__).with_name('settings.py')))

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            storage = StorageHandler(backends=production['STORAGES'])['default']
            name = storage.save('destinations/cover.png', ContentFile(b'cover image'))
            self.assertEqual((Path(media_root) / name).read_bytes(), b'cover image')
            self.assertTrue(storage.url(name).endswith('/destinations/cover.png'))


class ApiRootTests(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def test_api_root_reports_health_endpoint(self):
        response = api_root(self.request_factory.get('/'))

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {
            'service': 'Travel Osmena API',
            'status': 'online',
            'health': '/api/health/',
        })

    def test_api_root_accepts_head_health_checks(self):
        response = api_root(self.request_factory.head('/'))

        self.assertEqual(response.status_code, 200)


class ApiDocumentationTests(SimpleTestCase):
    @override_settings(
        ALLOWED_HOSTS=['api.touristspot.site'],
        SECURE_SSL_REDIRECT=False,
    )
    def test_openapi_schema_lists_the_existing_api(self):
        response = self.client.get(
            '/api/schema/',
            secure=True,
            HTTP_HOST='api.touristspot.site',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/json')
        schema = response.json()
        self.assertEqual(schema['openapi'], '3.1.0')
        self.assertEqual(schema['servers'][0]['url'], 'https://api.touristspot.site')
        self.assertIn('/api/health/', schema['paths'])
        self.assertIn('/api/auth/login/', schema['paths'])
        self.assertIn('/api/admin/destinations/{destination_id}/', schema['paths'])
        self.assertIn('sessionCookie', schema['components']['securitySchemes'])
        self.assertIn('csrfHeader', schema['components']['securitySchemes'])
        application_paths = {
            f"/api/{str(pattern.pattern).replace('<int:destination_id>', '{destination_id}')}"
            for pattern in itinerary_urlpatterns
        }
        self.assertTrue(application_paths.issubset(schema['paths']))
        operation_ids = [
            operation['operationId']
            for path_item in schema['paths'].values()
            for operation in path_item.values()
        ]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))

    def test_swagger_ui_loads_the_local_schema(self):
        response = self.client.get('/api/docs/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'SwaggerUIBundle')
        self.assertContains(response, '/api/schema/')
        self.assertEqual(response.headers['X-Robots-Tag'], 'noindex, nofollow')
        self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])


class CorsConfigurationTests(SimpleTestCase):
    @override_settings(
        CORS_ALLOWED_ORIGINS=['https://touristspot.site'],
        CORS_ALLOW_CREDENTIALS=True,
    )
    def test_frontend_origin_is_allowed_with_credentials(self):
        response = self.client.options(
            '/api/auth/csrf/',
            HTTP_ORIGIN='https://touristspot.site',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET',
        )

        self.assertEqual(
            response.headers['Access-Control-Allow-Origin'],
            'https://touristspot.site',
        )
        self.assertEqual(response.headers['Access-Control-Allow-Credentials'], 'true')

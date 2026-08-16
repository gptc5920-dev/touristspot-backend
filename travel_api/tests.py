from django.test import RequestFactory, SimpleTestCase, override_settings

from .views import api_root


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

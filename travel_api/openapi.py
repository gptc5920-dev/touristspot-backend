"""OpenAPI metadata for the plain-Django JSON API.

The project intentionally does not depend on Django REST Framework. Keeping the
description here gives API consumers a machine-readable contract and an
interactive viewer without changing the existing request handlers.
"""


GENERIC_OBJECT = {'type': 'object', 'additionalProperties': True}


def _endpoint(
    path,
    method,
    operation_id,
    tag,
    summary,
    *,
    description='',
    request_schema=None,
    request_content_type='application/json',
    response_schema=None,
    success_status='200',
    security=None,
):
    return {
        'path': path,
        'method': method,
        'operation_id': operation_id,
        'tag': tag,
        'summary': summary,
        'description': description,
        'request_schema': request_schema,
        'request_content_type': request_content_type,
        'response_schema': response_schema,
        'success_status': success_status,
        'security': security,
    }


ENDPOINTS = [
    _endpoint('/', 'get', 'apiRoot', 'System', 'API service summary', response_schema='ApiRoot'),
    _endpoint('/api/schema/', 'get', 'openApiSchema', 'System', 'OpenAPI schema'),
    _endpoint('/api/docs/', 'get', 'swaggerUi', 'System', 'Interactive API documentation'),
    _endpoint('/api/health/', 'get', 'healthCheck', 'System', 'Service and database health', response_schema='Health'),
    _endpoint('/api/settings/', 'get', 'publicSettings', 'Public', 'Public site settings'),
    _endpoint('/api/auth/csrf/', 'get', 'csrfCookie', 'Authentication', 'Set the CSRF cookie', response_schema='CsrfResponse'),
    _endpoint('/api/auth/me/', 'get', 'currentUser', 'Authentication', 'Current session user', response_schema='UserEnvelope'),
    _endpoint(
        '/api/auth/signup/', 'post', 'signUp', 'Authentication', 'Create a tourist account',
        request_schema='SignupRequest', response_schema='UserEnvelope', success_status='201', security='csrf',
    ),
    _endpoint(
        '/api/auth/login/', 'post', 'logIn', 'Authentication', 'Sign in with username or email',
        request_schema='LoginRequest', response_schema='UserEnvelope', security='csrf',
    ),
    _endpoint(
        '/api/auth/logout/', 'post', 'logOut', 'Authentication', 'End the current session',
        response_schema='UserEnvelope', security='session_csrf',
    ),
    _endpoint(
        '/api/auth/password-reset/', 'post', 'requestPasswordReset', 'Authentication', 'Request a password reset email',
        request_schema='PasswordResetRequest', security='csrf',
    ),
    _endpoint(
        '/api/auth/password-reset/confirm/', 'post', 'confirmPasswordReset', 'Authentication', 'Set a new password using a reset token',
        request_schema='PasswordResetConfirmRequest', security='csrf',
    ),
    _endpoint('/api/tourist/profile/', 'get', 'touristProfile', 'Tourist', 'Get the signed-in tourist profile', security='session'),
    _endpoint(
        '/api/tourist/profile/', 'patch', 'updateTouristProfile', 'Tourist', 'Update the signed-in tourist profile',
        request_schema='GenericObject', security='session_csrf',
    ),
    _endpoint('/api/tourist/preferences/', 'get', 'touristPreferences', 'Tourist', 'Get itinerary preferences', security='session'),
    _endpoint(
        '/api/tourist/preferences/', 'post', 'createTouristPreferences', 'Tourist', 'Save itinerary preferences',
        request_schema='GenericObject', security='session_csrf',
    ),
    _endpoint(
        '/api/tourist/preferences/', 'put', 'replaceTouristPreferences', 'Tourist', 'Replace itinerary preferences',
        request_schema='GenericObject', security='session_csrf',
    ),
    _endpoint('/api/tourist/recommendations/', 'get', 'touristRecommendations', 'Tourist', 'Get personalized recommendations', security='session'),
    _endpoint(
        '/api/tourist/recommendations/generate/', 'post', 'generateTouristRecommendations', 'Tourist', 'Regenerate personalized recommendations',
        security='session_csrf',
    ),
    _endpoint('/api/destinations/', 'get', 'destinationList', 'Destinations', 'List active verified destinations', response_schema='DestinationList'),
    _endpoint('/api/destinations/{destination_id}/feedback/', 'get', 'destinationFeedback', 'Destinations', 'Get destination reviews and rating summary'),
    _endpoint(
        '/api/destinations/{destination_id}/feedback/', 'post', 'saveDestinationFeedback', 'Destinations', 'Create or update tourist feedback',
        request_schema='FeedbackRequest', security='session_csrf',
    ),
    _endpoint(
        '/api/itineraries/generate/', 'post', 'generateItinerary', 'Itineraries', 'Generate an itinerary',
        request_schema='GenericObject', security='csrf',
    ),
    _endpoint('/api/itineraries/', 'get', 'savedItineraries', 'Itineraries', 'List the current user\'s saved itineraries', security='session'),
    _endpoint(
        '/api/itineraries/', 'post', 'saveItinerary', 'Itineraries', 'Save an itinerary',
        request_schema='GenericObject', success_status='201', security='session_csrf',
    ),
    _endpoint('/api/admin/dashboard/', 'get', 'adminDashboard', 'Administration', 'Tourism dashboard summary', security='session'),
    _endpoint('/api/admin/users/', 'get', 'adminUsers', 'Administration', 'List accounts and activity', security='session'),
    _endpoint('/api/admin/settings/', 'get', 'adminSettings', 'Administration', 'Get editable site settings', security='session'),
    _endpoint(
        '/api/admin/settings/', 'patch', 'updateAdminSettings', 'Administration', 'Update site settings',
        request_schema='GenericObject', security='session_csrf',
    ),
    _endpoint(
        '/api/admin/settings/logo/', 'post', 'uploadAdminLogo', 'Administration', 'Upload the site logo',
        request_schema='LogoUpload', request_content_type='multipart/form-data', security='session_csrf',
    ),
    _endpoint('/api/admin/settings/logo/', 'delete', 'deleteAdminLogo', 'Administration', 'Remove the site logo', security='session_csrf'),
    _endpoint('/api/admin/destinations/', 'get', 'adminDestinations', 'Administration', 'List all destinations', security='session'),
    _endpoint(
        '/api/admin/destinations/', 'post', 'createAdminDestination', 'Administration', 'Create a destination',
        request_schema='DestinationInput', response_schema='DestinationEnvelope', success_status='201', security='session_csrf',
    ),
    _endpoint(
        '/api/admin/destinations/{destination_id}/', 'patch', 'updateAdminDestination', 'Administration', 'Update a destination',
        request_schema='DestinationInput', response_schema='DestinationEnvelope', security='session_csrf',
    ),
    _endpoint('/api/admin/destinations/{destination_id}/', 'delete', 'deleteAdminDestination', 'Administration', 'Delete a destination', security='session_csrf'),
    _endpoint(
        '/api/admin/destinations/{destination_id}/image/', 'post', 'uploadAdminDestinationImage', 'Administration', 'Upload a destination cover image',
        request_schema='ImageUpload', request_content_type='multipart/form-data', response_schema='DestinationEnvelope', security='session_csrf',
    ),
    _endpoint(
        '/api/admin/destinations/{destination_id}/image/', 'delete', 'deleteAdminDestinationImage', 'Administration', 'Remove a destination cover image',
        response_schema='DestinationEnvelope', security='session_csrf',
    ),
]


SCHEMAS = {
    'GenericObject': GENERIC_OBJECT,
    'Error': {
        'type': 'object',
        'properties': {
            'error': {'type': 'string'},
            'message': {'type': 'string'},
            'errors': GENERIC_OBJECT,
        },
    },
    'ApiRoot': {
        'type': 'object',
        'required': ['service', 'status', 'health'],
        'properties': {
            'service': {'type': 'string', 'example': 'Travel Osmena API'},
            'status': {'type': 'string', 'example': 'online'},
            'health': {'type': 'string', 'example': '/api/health/'},
        },
    },
    'Health': {
        'type': 'object',
        'required': ['status', 'database'],
        'properties': {
            'status': {'type': 'string', 'enum': ['healthy', 'degraded']},
            'database': {'type': 'string', 'enum': ['connected', 'unavailable']},
            'itinerary_service': {'type': 'string'},
            'recommendation_model': {'type': 'string'},
            'map_service': {'type': 'string'},
            'version': {'type': 'string'},
        },
    },
    'CsrfResponse': {
        'type': 'object',
        'properties': {'detail': {'type': 'string', 'example': 'CSRF cookie set.'}},
    },
    'User': {
        'type': 'object',
        'required': ['is_authenticated', 'role'],
        'properties': {
            'is_authenticated': {'type': 'boolean'},
            'username': {'type': 'string'},
            'email': {'type': 'string', 'format': 'email'},
            'display_name': {'type': 'string'},
            'role': {'type': 'string', 'enum': ['guest', 'tourist', 'admin']},
            'preferences_completed': {'type': 'boolean'},
        },
    },
    'UserEnvelope': {
        'type': 'object',
        'properties': {'user': {'$ref': '#/components/schemas/User'}},
    },
    'SignupRequest': {
        'type': 'object',
        'required': ['full_name', 'username', 'email', 'password', 'password_confirm'],
        'properties': {
            'full_name': {'type': 'string', 'minLength': 2, 'maxLength': 120},
            'username': {'type': 'string', 'minLength': 3, 'maxLength': 150},
            'email': {'type': 'string', 'format': 'email'},
            'password': {'type': 'string', 'format': 'password'},
            'password_confirm': {'type': 'string', 'format': 'password'},
        },
    },
    'LoginRequest': {
        'type': 'object',
        'required': ['identifier', 'password'],
        'properties': {
            'identifier': {'type': 'string', 'description': 'Username or email address.'},
            'password': {'type': 'string', 'format': 'password'},
            'remember_me': {'type': 'boolean', 'default': False},
        },
    },
    'PasswordResetRequest': {
        'type': 'object',
        'required': ['email'],
        'properties': {'email': {'type': 'string', 'format': 'email'}},
    },
    'PasswordResetConfirmRequest': {
        'type': 'object',
        'required': ['uid', 'token', 'password', 'password_confirm'],
        'properties': {
            'uid': {'type': 'string'},
            'token': {'type': 'string'},
            'password': {'type': 'string', 'format': 'password'},
            'password_confirm': {'type': 'string', 'format': 'password'},
        },
    },
    'Destination': {
        'type': 'object',
        'required': ['id', 'name', 'description', 'category', 'coordinates'],
        'properties': {
            'id': {'type': 'integer'},
            'name': {'type': 'string'},
            'description': {'type': 'string'},
            'category': {'type': 'string'},
            'interests': {'type': 'array', 'items': {'type': 'string'}},
            'address': {'type': 'string'},
            'coordinates': {'type': 'array', 'prefixItems': [{'type': 'number'}, {'type': 'number'}], 'minItems': 2, 'maxItems': 2},
            'opening_time': {'type': 'string', 'format': 'time'},
            'closing_time': {'type': 'string', 'format': 'time'},
            'entrance_fee': {'type': 'number'},
            'image_url': {'type': 'string'},
            'is_active': {'type': 'boolean'},
            'is_verified': {'type': 'boolean'},
            'review_count': {'type': 'integer'},
            'average_rating': {'type': ['number', 'null']},
        },
        'additionalProperties': True,
    },
    'DestinationList': {
        'type': 'object',
        'properties': {'destinations': {'type': 'array', 'items': {'$ref': '#/components/schemas/Destination'}}},
    },
    'DestinationEnvelope': {
        'type': 'object',
        'properties': {'destination': {'$ref': '#/components/schemas/Destination'}},
    },
    'DestinationInput': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'maxLength': 180},
            'description': {'type': 'string'},
            'category': {'type': 'string'},
            'interests': {'type': 'array', 'items': {'type': 'string'}},
            'area': {'type': 'string'},
            'address': {'type': 'string'},
            'latitude': {'type': 'number', 'minimum': -90, 'maximum': 90},
            'longitude': {'type': 'number', 'minimum': -180, 'maximum': 180},
            'opening_time': {'type': 'string', 'format': 'time'},
            'closing_time': {'type': 'string', 'format': 'time'},
            'operating_days': {'type': 'array', 'items': {'type': 'string'}},
            'visit_minutes': {'type': 'integer', 'minimum': 1},
            'entrance_fee': {'type': 'number', 'minimum': 0},
            'is_active': {'type': 'boolean'},
            'is_verified': {'type': 'boolean'},
        },
        'additionalProperties': True,
    },
    'FeedbackRequest': {
        'type': 'object',
        'required': ['rating'],
        'properties': {
            'rating': {'type': 'integer', 'minimum': 1, 'maximum': 5},
            'comment': {'type': 'string', 'maxLength': 1200},
            'suggestion': {'type': 'string', 'maxLength': 1200},
        },
    },
    'LogoUpload': {
        'type': 'object',
        'required': ['logo'],
        'properties': {'logo': {'type': 'string', 'format': 'binary'}},
    },
    'ImageUpload': {
        'type': 'object',
        'required': ['image'],
        'properties': {'image': {'type': 'string', 'format': 'binary'}},
    },
}


def _schema_reference(name):
    if not name:
        return GENERIC_OBJECT
    return {'$ref': f'#/components/schemas/{name}'}


def _json_response(description, schema=None):
    response = {'description': description}
    if schema:
        response['content'] = {'application/json': {'schema': schema}}
    return response


def _security_requirement(name):
    if name == 'session':
        return [{'sessionCookie': []}]
    if name == 'csrf':
        return [{'csrfHeader': []}]
    if name == 'session_csrf':
        return [{'sessionCookie': [], 'csrfHeader': []}]
    return None


def build_openapi_schema(server_url):
    paths = {}
    for endpoint in ENDPOINTS:
        operation = {
            'operationId': endpoint['operation_id'],
            'tags': [endpoint['tag']],
            'summary': endpoint['summary'],
            'responses': {
                endpoint['success_status']: _json_response(
                    'Successful response.',
                    _schema_reference(endpoint['response_schema']),
                ),
            },
        }
        if endpoint['description']:
            operation['description'] = endpoint['description']
        if endpoint['request_schema']:
            operation['requestBody'] = {
                'required': True,
                'content': {
                    endpoint['request_content_type']: {
                        'schema': _schema_reference(endpoint['request_schema']),
                    },
                },
            }
            operation['responses']['400'] = _json_response(
                'Request validation failed.',
                _schema_reference('Error'),
            )
        if '{destination_id}' in endpoint['path']:
            operation['parameters'] = [{
                'name': 'destination_id',
                'in': 'path',
                'required': True,
                'description': 'Destination identifier.',
                'schema': {'type': 'integer', 'minimum': 1},
            }]
            operation['responses']['404'] = _json_response(
                'Destination not found.',
                _schema_reference('Error'),
            )
        security = _security_requirement(endpoint['security'])
        if security:
            operation['security'] = security
        if endpoint['security'] in {'session', 'session_csrf'}:
            operation['responses']['401'] = _json_response(
                'Authentication is required.',
                _schema_reference('Error'),
            )
            if endpoint['tag'] in {'Tourist', 'Administration'}:
                operation['responses']['403'] = _json_response(
                    'The signed-in account does not have the required role.',
                    _schema_reference('Error'),
                )
        paths.setdefault(endpoint['path'], {})[endpoint['method']] = operation

    return {
        'openapi': '3.1.0',
        'info': {
            'title': 'Travel Osmena API',
            'version': '1.1.0',
            'description': (
                'Tourist destinations, itinerary generation, traveler accounts, '
                'and staff administration. For browser requests, call '
                '`GET /api/auth/csrf/` before a state-changing operation.'
            ),
        },
        'servers': [{'url': server_url, 'description': 'Current server'}],
        'tags': [
            {'name': 'System'},
            {'name': 'Public'},
            {'name': 'Authentication'},
            {'name': 'Tourist'},
            {'name': 'Destinations'},
            {'name': 'Itineraries'},
            {'name': 'Administration'},
        ],
        'paths': paths,
        'components': {
            'securitySchemes': {
                'sessionCookie': {
                    'type': 'apiKey',
                    'in': 'cookie',
                    'name': 'sessionid',
                    'description': 'Django session cookie returned after login.',
                },
                'csrfHeader': {
                    'type': 'apiKey',
                    'in': 'header',
                    'name': 'X-CSRFToken',
                    'description': 'Value of the csrftoken cookie.',
                },
            },
            'schemas': SCHEMAS,
        },
    }


SWAGGER_UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>Travel Osmena API documentation</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui.css">
  <style>html { box-sizing: border-box; overflow-y: scroll; } body { margin: 0; background: #fafafa; }</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-bundle.js" crossorigin></script>
  <script>
    window.onload = () => {
      const csrfToken = () => {
        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
      };
      window.ui = SwaggerUIBundle({
        url: __SCHEMA_URL__,
        dom_id: '#swagger-ui',
        deepLinking: true,
        displayRequestDuration: true,
        docExpansion: 'list',
        filter: true,
        persistAuthorization: false,
        validatorUrl: null,
        withCredentials: true,
        requestInterceptor: (request) => {
          const method = (request.method || 'GET').toUpperCase();
          if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method) && csrfToken()) {
            request.headers['X-CSRFToken'] = csrfToken();
          }
          return request;
        },
      });
    };
  </script>
</body>
</html>
"""


def swagger_ui_html(schema_url):
    # The URL comes from Django's route resolver rather than user input.
    return SWAGGER_UI_HTML.replace('__SCHEMA_URL__', repr(schema_url))

"""
URL configuration for travel_api project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('itineraries.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# The Vite frontend uses the browser History API. Serving its index document
# here keeps deep links such as /planner/ and /admin-dashboard/ working after a
# refresh, while API, admin, static, and upload paths remain server-owned.
if (settings.BASE_DIR.parent / 'frontend' / 'dist' / 'index.html').is_file():
    urlpatterns += [
        re_path(
            r'^(?!api(?:/|$)|admin(?:/|$)|static(?:/|$)|media(?:/|$)).*$',
            TemplateView.as_view(template_name='index.html'),
            name='frontend-app',
        ),
    ]
else:
    # Backend-only deployments (including the Nixpacks service) should expose a
    # successful root response instead of relying on a separate frontend build.
    urlpatterns += [path('', views.api_root, name='api-root')]

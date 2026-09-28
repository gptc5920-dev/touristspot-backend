from django.urls import path

from . import locations, views

urlpatterns = [
    path('locations/provinces/', locations.provinces, name='location-provinces'),
    path('locations/municipalities/', locations.municipalities, name='location-municipalities'),
    path('locations/barangays/', locations.barangays, name='location-barangays'),
    path('health/', views.health, name='health'),
    path('settings/', views.public_settings, name='public-settings'),
    path('auth/csrf/', views.csrf, name='csrf'),
    path('auth/me/', views.current_user, name='current-user'),
    path('auth/signup/', views.signup_view, name='signup'),
    path('auth/login/', views.login_view, name='login'),
    path('auth/logout/', views.logout_view, name='logout'),
    path('auth/password-reset/', views.password_reset_request, name='password-reset'),
    path('auth/password-reset/confirm/', views.password_reset_confirm, name='password-reset-confirm'),
    path('tourist/profile/', views.tourist_profile, name='tourist-profile'),
    path('tourist/preferences/', views.tourist_preferences, name='tourist-preferences'),
    path('tourist/recommendations/', views.tourist_recommendations, name='tourist-recommendations'),
    path('tourist/recommendations/generate/', views.generate_tourist_recommendations, name='generate-tourist-recommendations'),
    path('destinations/', views.destination_list, name='destination-list'),
    path('destinations/<int:destination_id>/feedback/', views.destination_feedback, name='destination-feedback'),
    path('itineraries/generate/', views.generate_itinerary, name='generate-itinerary'),
    path('itineraries/', views.saved_itineraries, name='saved-itineraries'),
    path('admin/dashboard/', views.admin_dashboard, name='admin-dashboard'),
    path('admin/users/', views.admin_users, name='admin-users'),
    path('admin/settings/', views.admin_settings, name='admin-settings'),
    path('admin/settings/logo/', views.admin_settings_logo, name='admin-settings-logo'),
    path('admin/destinations/', views.admin_destinations, name='admin-destinations'),
    path('admin/destinations/<int:destination_id>/', views.admin_destination_detail, name='admin-destination-detail'),
    path('admin/destinations/<int:destination_id>/image/', views.admin_destination_image, name='admin-destination-image'),
]

import json
import re
import tempfile
from datetime import time
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from .models import Destination, DestinationReview, SavedItinerary, SiteSettings, TouristProfile


class ItineraryApiTests(TestCase):
    def setUp(self):
        Destination.objects.create(
            name='Test Falls', description='A verified nature stop.', category='Nature',
            interests=['nature'], address='Test address', latitude=9.7, longitude=123.4,
            opening_time=time(8), closing_time=time(17), operating_days=['Thursday'],
            visit_minutes=90, entrance_fee=50, activities=['Sightseeing'], is_active=True,
            is_verified=True, recommended_companions=['couple'], area='Test Area',
        )

    def preference_request(self, **overrides):
        payload = {
            'selected_interests': ['nature', 'photography'],
            'preferred_categories': ['Nature & eco-tourism'],
            'budget_min': 0,
            'budget_max': 1500,
            'available_start_time': '08:00',
            'available_end_time': '17:00',
            'travel_pace': 'balanced',
            'transportation_preference': 'public',
            'traveler_type': 'couple',
            'accessibility_requirements': '',
            'preferred_language': 'English',
            'starting_location': 'Town center',
            'latitude': 9.70,
            'longitude': 123.40,
        }
        payload.update(overrides)
        return payload

    def create_tourist_with_preferences(self, username='preference-tourist', **overrides):
        user = get_user_model().objects.create_user(username=username, password='secure-pass')
        self.client.force_login(user)
        response = self.client.post(
            '/api/tourist/preferences/',
            data=json.dumps(self.preference_request(**overrides)),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        return user

    def test_lists_verified_active_destinations(self):
        response = self.client.get('/api/destinations/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Test Falls', [item['name'] for item in response.json()['destinations']])

    def test_public_settings_exposes_default_branding(self):
        response = self.client.get('/api/settings/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['settings']['site_name'], 'Travel Osmena')
        self.assertFalse(response.json()['settings']['has_logo'])

    def test_generates_an_itinerary(self):
        response = self.client.post('/api/itineraries/generate/', data=json.dumps({
            'travel_date': '2026-08-20', 'starting_location': 'Dalaguete town center',
            'start_time': '08:00', 'end_time': '17:00', 'interests': ['nature'],
            'companion': 'couple', 'transportation': 'public', 'pace': 'balanced', 'language': 'English', 'budget': 1000,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()['itinerary']['summary']['destinations'], 0)
        itinerary = response.json()['itinerary']
        destination_stop = next(stop for stop in itinerary['stops'] if stop['type'] == 'destination')
        self.assertEqual(itinerary['summary']['recommendation_engine']['name'], 'hybrid')
        self.assertGreater(destination_stop['recommendation']['match_percent'], 0)
        self.assertTrue(destination_stop['recommendation']['reasons'])

    def test_hybrid_recommender_uses_similar_saved_itineraries(self):
        popular = Destination.objects.create(
            name='Popular Garden', description='A verified nature stop.', category='Nature',
            interests=['nature'], address='Garden road', latitude=9.71, longitude=123.41,
            opening_time=time(8), closing_time=time(17), operating_days=['Thursday'],
            visit_minutes=90, entrance_fee=50, activities=['Sightseeing'], is_active=True,
            is_verified=True, recommended_companions=['couple'], area='Test Area',
        )
        SavedItinerary.objects.create(
            name='Similar nature trip', travel_date='2026-08-20',
            preferences={'interests': ['nature'], 'companion': 'couple', 'transportation': 'public', 'pace': 'balanced'},
            itinerary={'map': [{'id': popular.id}]},
        )
        response = self.client.post('/api/itineraries/generate/', data=json.dumps({
            'travel_date': '2026-08-20', 'starting_location': 'Town center',
            'start_time': '08:00', 'end_time': '17:00', 'travelers': 1,
            'interests': ['nature'], 'companion': 'couple', 'transportation': 'public',
            'pace': 'balanced', 'language': 'English', 'budget': 1000,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        itinerary = response.json()['itinerary']
        first_destination = next(stop for stop in itinerary['stops'] if stop['type'] == 'destination')
        self.assertEqual(first_destination['id'], popular.id)
        self.assertTrue(itinerary['summary']['recommendation_engine']['collaborative_enabled'])
        self.assertIn('Popular in similar saved trips', first_destination['recommendation']['reasons'])

    def test_budget_totals_entrance_fees_for_the_whole_group(self):
        response = self.client.post('/api/itineraries/generate/', data=json.dumps({
            'travel_date': '2026-08-20', 'starting_location': 'Town center',
            'start_time': '08:00', 'end_time': '17:00', 'travelers': 2,
            'interests': ['nature'], 'companion': 'couple', 'transportation': 'public',
            'pace': 'balanced', 'language': 'English', 'budget': 1000,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['itinerary']['budget']['entrance_fees'], 100.0)

    def test_generation_rejects_invalid_schedule_and_unknown_destination(self):
        response = self.client.post('/api/itineraries/generate/', data=json.dumps({
            'travel_date': '2026-08-20', 'starting_location': 'Town center',
            'start_time': '17:00', 'end_time': '08:00', 'travel_days': 1, 'travelers': 1,
            'interests': ['nature'], 'preferred_destinations': [999], 'excluded_destinations': [],
            'budget': 1000, 'transportation': 'public', 'pace': 'balanced', 'language': 'English',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('end_time', response.json()['errors'])
        self.assertIn('preferred_destinations', response.json()['errors'])

    def test_generation_rejects_duplicate_destination_ids(self):
        response = self.client.post('/api/itineraries/generate/', data=json.dumps({
            'travel_date': '2026-08-20', 'starting_location': 'Town center',
            'start_time': '08:00', 'end_time': '17:00', 'travel_days': 1, 'travelers': 1,
            'interests': ['nature'], 'preferred_destinations': [1, 1], 'excluded_destinations': [],
            'budget': 1000, 'transportation': 'public', 'pace': 'balanced', 'language': 'English',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('preferred_destinations', response.json()['errors'])

    def test_saved_itineraries_require_sign_in(self):
        response = self.client.get('/api/itineraries/')
        self.assertEqual(response.status_code, 401)

    def test_admin_dashboard_requires_staff_role(self):
        User = get_user_model()
        tourist = User.objects.create_user(username='traveler', password='secure-pass')
        self.client.force_login(tourist)
        response = self.client.get('/api/admin/dashboard/')
        self.assertEqual(response.status_code, 403)

        tourist.is_staff = True
        tourist.save()
        response = self.client.get('/api/admin/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('stats', response.json())
        self.assertEqual(response.json()['stats']['ready_destinations'], 1)
        self.assertEqual(response.json()['stats']['readiness_percent'], 100)
        self.assertEqual(response.json()['category_counts'][0], {'category': 'Nature', 'count': 1})

    def test_admin_dashboard_reports_records_that_need_attention(self):
        User = get_user_model()
        staff = User.objects.create_user(username='office-admin', password='secure-pass', is_staff=True)
        Destination.objects.create(
            name='Pending Museum', description='Awaiting office verification.', category='History',
            interests=['history'], address='Museum road', latitude=9.71, longitude=123.41,
            opening_time=time(8), closing_time=time(17), operating_days=['Thursday'],
            visit_minutes=60, entrance_fee=25, activities=['Museum visit'], is_active=True,
            is_verified=False, recommended_companions=['family'], area='Town Center',
        )
        self.client.force_login(staff)
        response = self.client.get('/api/admin/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['stats']['pending_destinations'], 1)
        self.assertEqual(response.json()['attention_items'][0]['issue'], 'Needs verification')

    def test_admin_users_table_lists_accounts_and_activity(self):
        self.assertEqual(self.client.get('/api/admin/users/').status_code, 401)
        User = get_user_model()
        staff = User.objects.create_user(username='users-admin', password='secure-pass', is_staff=True)
        tourist = User.objects.create_user(
            username='table-tourist', email='table@example.com', first_name='Table Tourist', password='secure-pass',
        )
        TouristProfile.objects.create(
            user=tourist, display_name='Table Tourist', home_location='Poblacion',
            interests=['nature', 'history'], preferred_pace='relaxed',
        )
        SavedItinerary.objects.create(
            owner=tourist, name='Nature day', travel_date='2026-08-20', preferences={}, itinerary={},
        )
        DestinationReview.objects.create(
            destination=Destination.objects.get(name='Test Falls'), author=tourist,
            rating=5, comment='Excellent destination.',
        )
        self.client.force_login(staff)
        response = self.client.get('/api/admin/users/')
        self.assertEqual(response.status_code, 200)
        record = next(item for item in response.json()['users'] if item['username'] == 'table-tourist')
        self.assertEqual(record['role'], 'tourist')
        self.assertEqual(record['interests'], ['nature', 'history'])
        self.assertEqual(record['saved_itinerary_count'], 1)
        self.assertEqual(record['review_count'], 1)

    def test_staff_login_sets_a_session_for_admin_routes(self):
        User = get_user_model()
        User.objects.create_user(username='admin-user', email='admin@example.com', password='secure-pass', is_staff=True)
        client = Client(enforce_csrf_checks=True)
        client.get('/api/auth/csrf/')
        response = client.post('/api/auth/login/', data=json.dumps({
            'email': 'admin@example.com', 'password': 'secure-pass',
        }), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['role'], 'admin')
        self.assertEqual(response.json()['user']['username'], 'admin-user')
        self.assertEqual(response.json()['user']['email'], 'admin@example.com')
        self.assertTrue(client.session.get_expire_at_browser_close())
        self.assertEqual(client.get('/api/admin/dashboard/').status_code, 200)

    @override_settings(REMEMBER_ME_SECONDS=1209600)
    def test_remember_me_controls_session_persistence(self):
        get_user_model().objects.create_user(
            username='remembered-user', email='remembered@example.com', password='secure-pass',
        )
        remembered_client = Client()
        response = remembered_client.post('/api/auth/login/', data=json.dumps({
            'identifier': 'remembered-user', 'password': 'secure-pass', 'remember_me': True,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(remembered_client.session.get_expire_at_browser_close())
        self.assertGreaterEqual(remembered_client.session.get_expiry_age(), 1209590)

        browser_client = Client()
        response = browser_client.post('/api/auth/login/', data=json.dumps({
            'identifier': 'remembered-user', 'password': 'secure-pass', 'remember_me': False,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(browser_client.session.get_expire_at_browser_close())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        FRONTEND_URL='http://frontend.test',
    )
    def test_password_reset_request_is_private_and_token_is_one_time(self):
        user = get_user_model().objects.create_user(
            username='reset-user', email='reset@example.com', password='Old-secure-pass-2026!',
        )
        response = self.client.post('/api/auth/password-reset/', data=json.dumps({
            'email': 'reset@example.com',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        reset_url = re.search(r'https?://\S+', mail.outbox[0].body).group(0)
        parsed_url = urlparse(reset_url)
        parameters = parse_qs(parsed_url.query)
        self.assertEqual(parsed_url.path, '/reset-password/')

        unknown_response = self.client.post('/api/auth/password-reset/', data=json.dumps({
            'email': 'unknown@example.com',
        }), content_type='application/json')
        self.assertEqual(unknown_response.status_code, 200)
        self.assertEqual(unknown_response.json(), response.json())
        self.assertEqual(len(mail.outbox), 1)

        reset_payload = {
            'uid': parameters['uid'][0],
            'token': parameters['token'][0],
            'password': 'New-secure-pass-2026!',
            'password_confirm': 'New-secure-pass-2026!',
        }
        confirm_response = self.client.post(
            '/api/auth/password-reset/confirm/',
            data=json.dumps(reset_payload),
            content_type='application/json',
        )
        self.assertEqual(confirm_response.status_code, 200, confirm_response.content)
        user.refresh_from_db()
        self.assertTrue(user.check_password('New-secure-pass-2026!'))

        reused_response = self.client.post(
            '/api/auth/password-reset/confirm/',
            data=json.dumps(reset_payload),
            content_type='application/json',
        )
        self.assertEqual(reused_response.status_code, 400)

    def test_password_reset_rejects_invalid_email_and_token(self):
        email_response = self.client.post('/api/auth/password-reset/', data=json.dumps({
            'email': 'not-an-email',
        }), content_type='application/json')
        self.assertEqual(email_response.status_code, 400)

        token_response = self.client.post('/api/auth/password-reset/confirm/', data=json.dumps({
            'uid': 'invalid', 'token': 'invalid',
            'password': 'New-secure-pass-2026!',
            'password_confirm': 'New-secure-pass-2026!',
        }), content_type='application/json')
        self.assertEqual(token_response.status_code, 400)

    def test_tourist_can_sign_up_and_receives_a_profile(self):
        response = self.client.post('/api/auth/signup/', data=json.dumps({
            'full_name': 'Maria Traveler', 'username': 'maria-traveler',
            'email': 'maria@example.com', 'password': 'Strong-pass-2026!',
            'password_confirm': 'Strong-pass-2026!',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['user']['role'], 'tourist')
        self.assertTrue(response.json()['user']['is_authenticated'])
        user = get_user_model().objects.get(username='maria-traveler')
        self.assertTrue(TouristProfile.objects.filter(user=user).exists())
        self.assertEqual(self.client.get('/api/tourist/profile/').status_code, 200)

    def test_first_time_login_marks_preference_onboarding_as_required(self):
        get_user_model().objects.create_user(username='first-login', password='secure-pass')
        response = self.client.post('/api/auth/login/', data=json.dumps({
            'identifier': 'first-login', 'password': 'secure-pass',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['user']['preferences_completed'])
        preference_response = self.client.get('/api/tourist/preferences/')
        self.assertTrue(preference_response.json()['onboarding_required'])

    def test_incomplete_preferences_cannot_be_saved(self):
        user = get_user_model().objects.create_user(username='incomplete-tourist', password='secure-pass')
        self.client.force_login(user)
        response = self.client.post('/api/tourist/preferences/', data=json.dumps({
            'selected_interests': [], 'preferred_categories': [],
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('selected_interests', response.json()['errors'])
        self.assertIn('preferred_categories', response.json()['errors'])
        self.assertFalse(TouristProfile.objects.get(user=user).onboarding_completed)

    def test_valid_preferences_are_saved_without_duplicate_profile_records(self):
        user = get_user_model().objects.create_user(username='save-preferences', password='secure-pass')
        TouristProfile.objects.create(user=user)
        self.client.force_login(user)
        for method in ('post', 'put'):
            response = getattr(self.client, method)(
                '/api/tourist/preferences/', data=json.dumps(self.preference_request()),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()['preferences']['onboarding_completed'])
            self.assertTrue(response.json()['user']['preferences_completed'])
        self.assertEqual(TouristProfile.objects.filter(user=user).count(), 1)

    def test_recommendations_rank_selected_interests_first(self):
        food_destination = Destination.objects.create(
            name='Food Market', description='A verified local dining experience.', category='Food & dining',
            interests=['food', 'shopping'], address='Market road', latitude=9.9, longitude=123.6,
            opening_time=time(8), closing_time=time(17), operating_days=['Thursday'], visit_minutes=90,
            entrance_fee=100, activities=['Food tasting'], is_active=True, is_verified=True,
            recommended_companions=['Families'], area='Market Area',
        )
        self.create_tourist_with_preferences()
        response = self.client.get('/api/tourist/recommendations/')
        self.assertEqual(response.status_code, 200, response.content)
        recommendations = response.json()['recommendations']
        self.assertEqual(recommendations[0]['destination_name'], 'Test Falls')
        self.assertGreaterEqual(recommendations[0]['match_score'], recommendations[1]['match_score'])
        self.assertIn(food_destination.id, [item['destination_id'] for item in recommendations])

    def test_inactive_or_unverified_destinations_are_never_recommended(self):
        inactive = Destination.objects.create(
            name='Closed Trail', description='This destination is not currently open.', category='Nature & eco-tourism',
            interests=['nature'], address='Closed road', latitude=9.8, longitude=123.5,
            opening_time=time(8), closing_time=time(17), operating_days=['Thursday'], visit_minutes=60,
            entrance_fee=0, activities=['Walking'], is_active=False, is_verified=True,
            recommended_companions=['Couples'], area='Closed Area',
        )
        unverified = Destination.objects.create(
            name='Draft Viewpoint', description='This destination still needs office verification.', category='Mountain & viewpoint',
            interests=['nature', 'photography'], address='Draft road', latitude=9.81, longitude=123.51,
            opening_time=time(8), closing_time=time(17), operating_days=['Thursday'], visit_minutes=60,
            entrance_fee=0, activities=['Photography'], is_active=True, is_verified=False,
            recommended_companions=['Couples'], area='Draft Area',
        )
        self.create_tourist_with_preferences(username='verified-only-tourist')
        destination_ids = [item['destination_id'] for item in self.client.get('/api/tourist/recommendations/').json()['recommendations']]
        self.assertNotIn(inactive.id, destination_ids)
        self.assertNotIn(unverified.id, destination_ids)

    def test_unknown_ai_destination_ids_are_rejected(self):
        self.create_tourist_with_preferences(username='unknown-id-tourist')
        with patch('itineraries.views.build_preference_recommendations', return_value=([{
            'destination_id': 999999,
            'match_score': 100,
            'recommendation_reason': 'Invented result.',
        }], {'name': 'test-service'})):
            response = self.client.get('/api/tourist/recommendations/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['recommendations'], [])
        self.assertEqual(response.json()['invalid_recommendation_count'], 1)

    def test_returning_tourist_login_reports_completed_preferences(self):
        user = self.create_tourist_with_preferences(username='returning-tourist')
        self.client.logout()
        response = self.client.post('/api/auth/login/', data=json.dumps({
            'identifier': user.username, 'password': 'secure-pass',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['user']['preferences_completed'])

    def test_updating_preferences_recalculates_recommendation_order(self):
        Destination.objects.create(
            name='Local Food Hall', description='A popular place for local flavors and delicacies.', category='Food & dining',
            interests=['food'], address='Food street', latitude=9.71, longitude=123.41,
            opening_time=time(8), closing_time=time(17), operating_days=['Thursday'], visit_minutes=90,
            entrance_fee=50, activities=['Food tasting'], is_active=True, is_verified=True,
            recommended_companions=['Couples'], area='Town Center',
        )
        user = self.create_tourist_with_preferences(username='update-tourist')
        first_response = self.client.get('/api/tourist/recommendations/').json()
        self.assertEqual(first_response['recommendations'][0]['destination_name'], 'Test Falls')
        update_response = self.client.put('/api/tourist/preferences/', data=json.dumps(self.preference_request(
            selected_interests=['food'], preferred_categories=['Food & dining'],
        )), content_type='application/json')
        self.assertEqual(update_response.status_code, 200)
        refreshed = self.client.post('/api/tourist/recommendations/generate/').json()
        self.assertEqual(refreshed['recommendations'][0]['destination_name'], 'Local Food Hall')
        self.assertEqual(TouristProfile.objects.filter(user=user).count(), 1)

    def test_tourists_only_receive_their_own_preferences(self):
        self.create_tourist_with_preferences(username='owner-tourist', selected_interests=['nature'])
        second_user = get_user_model().objects.create_user(username='other-tourist', password='secure-pass')
        self.client.force_login(second_user)
        response = self.client.get('/api/tourist/preferences/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['preferences']['selected_interests'], [])
        self.assertTrue(response.json()['onboarding_required'])

    def test_recommendation_timeout_returns_verified_popular_fallback(self):
        self.create_tourist_with_preferences(username='fallback-tourist')
        with patch('itineraries.views.build_preference_recommendations', side_effect=TimeoutError('service timeout')):
            response = self.client.get('/api/tourist/recommendations/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['fallback'])
        self.assertFalse(response.json()['personalized'])
        self.assertIn('temporarily unavailable', response.json()['message'])
        self.assertEqual(response.json()['recommendations'][0]['destination_name'], 'Test Falls')

    def test_empty_recommendations_return_clear_message(self):
        self.create_tourist_with_preferences(username='empty-results-tourist')
        Destination.objects.update(is_active=False)
        response = self.client.get('/api/tourist/recommendations/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['recommendations'], [])
        self.assertIn('No tourist destinations currently match', response.json()['message'])

    def test_signup_rejects_duplicate_email_and_weak_password(self):
        get_user_model().objects.create_user(
            username='existing-tourist', email='taken@example.com', password='Strong-pass-2026!',
        )
        response = self.client.post('/api/auth/signup/', data=json.dumps({
            'full_name': 'Another Tourist', 'username': 'another-tourist',
            'email': 'TAKEN@example.com', 'password': '123', 'password_confirm': '123',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.json()['errors'])
        self.assertIn('password', response.json()['errors'])

    def test_tourist_can_save_profile_preferences(self):
        tourist = get_user_model().objects.create_user(
            username='profile-tourist', email='profile@example.com', password='Strong-pass-2026!',
        )
        self.client.force_login(tourist)
        response = self.client.patch('/api/tourist/profile/', data=json.dumps({
            'full_name': 'Profile Tourist', 'email': 'profile@example.com',
            'home_location': 'Poblacion', 'bio': 'Weekend nature traveler.',
            'interests': ['nature', 'photography'], 'preferred_pace': 'relaxed',
            'preferred_transportation': 'private', 'preferred_language': 'Cebuano',
            'accessibility_needs': 'Frequent rest stops', 'typical_budget': 2500,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        profile = response.json()['profile']
        self.assertEqual(profile['interests'], ['nature', 'photography'])
        self.assertEqual(profile['preferred_pace'], 'relaxed')
        self.assertEqual(profile['typical_budget'], 2500.0)

    def test_tourist_can_rate_comment_and_suggest_for_a_destination(self):
        tourist = get_user_model().objects.create_user(
            username='review-tourist', email='review@example.com', password='Strong-pass-2026!',
        )
        destination = Destination.objects.get(name='Test Falls')
        anonymous_response = self.client.post(
            f'/api/destinations/{destination.id}/feedback/',
            data=json.dumps({'rating': 5}), content_type='application/json',
        )
        self.assertEqual(anonymous_response.status_code, 401)

        self.client.force_login(tourist)
        response = self.client.post(
            f'/api/destinations/{destination.id}/feedback/',
            data=json.dumps({
                'rating': 5, 'comment': 'Beautiful and easy to reach.',
                'suggestion': 'Add more shaded resting areas.',
            }), content_type='application/json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['average_rating'], 5.0)
        self.assertEqual(response.json()['review_count'], 1)
        self.assertEqual(response.json()['own_review']['suggestion'], 'Add more shaded resting areas.')
        self.assertEqual(DestinationReview.objects.filter(destination=destination, author=tourist).count(), 1)

        self.client.logout()
        public_response = self.client.get(f'/api/destinations/{destination.id}/feedback/')
        self.assertEqual(public_response.status_code, 200)
        self.assertNotIn('suggestion', public_response.json()['reviews'][0])
        listing = self.client.get('/api/destinations/').json()['destinations'][0]
        self.assertEqual(listing['average_rating'], 5.0)
        self.assertEqual(listing['review_count'], 1)

    def test_staff_login_accepts_the_trusted_vite_origin(self):
        User = get_user_model()
        User.objects.create_user(username='vite-admin', password='secure-pass', is_staff=True)
        client = Client(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1:8000')
        client.get('/api/auth/csrf/')
        response = client.post('/api/auth/login/', data=json.dumps({
            'identifier': 'vite-admin', 'password': 'secure-pass',
        }), content_type='application/json', HTTP_ORIGIN='http://localhost:5173',
            HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['username'], 'vite-admin')

    def test_staff_can_login_with_username(self):
        User = get_user_model()
        User.objects.create_user(username='office-admin', email='admin@example.com', password='secure-pass', is_staff=True)
        client = Client(enforce_csrf_checks=True)
        client.get('/api/auth/csrf/')
        response = client.post('/api/auth/login/', data=json.dumps({
            'identifier': 'office-admin', 'password': 'secure-pass',
        }), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['username'], 'office-admin')

    def test_duplicate_email_requires_username_when_password_matches_multiple_accounts(self):
        User = get_user_model()
        User.objects.create_user(username='first-admin', email='shared@example.com', password='secure-pass', is_staff=True)
        User.objects.create_user(username='second-admin', email='shared@example.com', password='secure-pass', is_staff=True)
        response = self.client.post('/api/auth/login/', data=json.dumps({
            'identifier': 'shared@example.com', 'password': 'secure-pass',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 409)
        self.assertIn('username', response.json()['error'])

    def test_csrf_rejection_returns_json(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post('/api/auth/login/', data=json.dumps({
            'email': 'admin@example.com', 'password': 'invalid',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['errors']['csrf'][0], 'Refresh the page if this message persists.')

    def test_admin_destination_validation_rejects_incomplete_records(self):
        User = get_user_model()
        staff = User.objects.create_user(username='office-admin', password='secure-pass', is_staff=True)
        self.client.force_login(staff)
        response = self.client.post('/api/admin/destinations/', data=json.dumps({
            'name': 'Incomplete place',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_staff_can_upload_and_remove_destination_cover_image(self):
        User = get_user_model()
        staff = User.objects.create_user(username='media-admin', password='secure-pass', is_staff=True)
        self.client.force_login(staff)
        destination = Destination.objects.get(name='Test Falls')
        image = SimpleUploadedFile(
            'test-cover.png', b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR', content_type='image/png',
        )

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(f'/api/admin/destinations/{destination.id}/image/', {'image': image})
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()['destination']['has_uploaded_image'])
            self.assertTrue(response.json()['destination']['image_url'].startswith('/media/destinations/'))

            response = self.client.delete(f'/api/admin/destinations/{destination.id}/image/')
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['destination']['has_uploaded_image'])

    def test_destination_upload_returns_json_when_media_storage_is_unavailable(self):
        User = get_user_model()
        staff = User.objects.create_user(username='storage-admin', password='secure-pass', is_staff=True)
        self.client.force_login(staff)
        destination = Destination.objects.get(name='Test Falls')
        image = SimpleUploadedFile(
            'test-cover.png', b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR', content_type='image/png',
        )

        with patch('django.core.files.storage.filesystem.FileSystemStorage._save', side_effect=OSError('read-only media')):
            with self.assertLogs('itineraries', level='ERROR'):
                response = self.client.post(f'/api/admin/destinations/{destination.id}/image/', {'image': image})

        self.assertEqual(response.status_code, 503)
        self.assertIn('storage is unavailable', response.json()['error'])
        destination.refresh_from_db()
        self.assertFalse(destination.image)

    def test_staff_can_update_settings_and_manage_logo(self):
        User = get_user_model()
        staff = User.objects.create_user(username='settings-admin', password='secure-pass', is_staff=True)
        tourist = User.objects.create_user(username='settings-tourist', password='secure-pass')
        self.client.force_login(tourist)
        self.assertEqual(self.client.get('/api/admin/settings/').status_code, 403)

        self.client.force_login(staff)
        response = self.client.patch('/api/admin/settings/', data=json.dumps({
            'site_name': 'Explore Osmena',
            'tagline': 'Plan a better local adventure.',
            'organization_name': 'Municipal Tourism Office',
            'municipality_name': 'Sergio Osmeña Sr., Zamboanga del Norte',
            'support_email': 'tourism@example.com',
            'support_phone': '+63 900 000 0000',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['settings']['site_name'], 'Explore Osmena')
        self.assertEqual(SiteSettings.objects.count(), 1)

        logo = SimpleUploadedFile(
            'tourism-logo.png', b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR', content_type='image/png',
        )
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post('/api/admin/settings/logo/', {'logo': logo})
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()['settings']['has_logo'])
            self.assertTrue(response.json()['settings']['logo_url'].startswith('/media/branding/'))

            response = self.client.delete('/api/admin/settings/logo/')
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['settings']['has_logo'])

    def test_staff_can_delete_a_destination(self):
        User = get_user_model()
        staff = User.objects.create_user(username='records-admin', password='secure-pass', is_staff=True)
        self.client.force_login(staff)
        destination = Destination.objects.get(name='Test Falls')

        response = self.client.delete(f'/api/admin/destinations/{destination.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], destination.id)
        self.assertFalse(Destination.objects.filter(id=destination.id).exists())

    def test_destination_cover_upload_rejects_non_image_content(self):
        User = get_user_model()
        staff = User.objects.create_user(username='media-reviewer', password='secure-pass', is_staff=True)
        self.client.force_login(staff)
        destination = Destination.objects.get(name='Test Falls')
        fake_image = SimpleUploadedFile('fake.png', b'not-an-image', content_type='image/png')
        response = self.client.post(f'/api/admin/destinations/{destination.id}/image/', {'image': fake_image})
        self.assertEqual(response.status_code, 400)
        self.assertIn('valid JPG, PNG, or WebP', response.json()['error'])

    def test_destination_availability_end_must_follow_start_date(self):
        User = get_user_model()
        staff = User.objects.create_user(username='calendar-admin', password='secure-pass', is_staff=True)
        self.client.force_login(staff)
        destination = Destination.objects.get(name='Test Falls')
        response = self.client.patch(f'/api/admin/destinations/{destination.id}/', data=json.dumps({
            'availability_start': '2026-12-20', 'availability_end': '2026-12-01',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('availability_end', response.json()['fields'])

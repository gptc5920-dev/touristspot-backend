import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib.auth import authenticate, get_user_model, login, logout, password_validation
from django.core.validators import validate_email
from django.db.models import Avg, Count, Q
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import Destination, DestinationReview, SavedItinerary, SiteSettings, TouristProfile
from .recommender import HybridRecommendationEngine, build_preference_recommendations


PACE_FACTORS = {'relaxed': 1.2, 'balanced': 1, 'fast': 0.8}
SUPPORTED_LANGUAGES = {'English', 'Filipino', 'Cebuano'}
SUPPORTED_PACES = set(PACE_FACTORS)
SUPPORTED_TRANSPORT = {'public', 'motorcycle', 'private', 'walking'}
SUPPORTED_TRAVELER_TYPES = {'solo', 'couple', 'family', 'friends', 'senior'}
MAX_TRAVELERS = 30
MAX_TEXT_LENGTH = 255
MAX_DESTINATION_IMAGE_BYTES = 5 * 1024 * 1024
MAX_SITE_LOGO_BYTES = 2 * 1024 * 1024
DESTINATION_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
SUPPORTED_INTERESTS = {
    'nature', 'history', 'food', 'adventure', 'religious',
    'water', 'family', 'photography', 'shopping', 'relaxation',
}
SUPPORTED_CATEGORIES = {
    'Nature & eco-tourism', 'Beach & coastal', 'Waterfall & river', 'Mountain & viewpoint',
    'Historical site', 'Cultural heritage', 'Religious site', 'Food & dining',
    'Adventure & recreation', 'Park & family attraction', 'Shopping & local products', 'Accommodation',
}
logger = logging.getLogger('itineraries')


def display_time(value):
    return value.strftime('%I:%M %p').lstrip('0')


def destination_available_on(destination, travel_date):
    return (
        (destination.availability_start is None or destination.availability_start <= travel_date)
        and (destination.availability_end is None or destination.availability_end >= travel_date)
    )


def destination_payload(destination):
    uploaded_image_url = destination.image.url if destination.image else ''
    if hasattr(destination, 'review_count'):
        review_count = destination.review_count
        average_rating = destination.average_rating
    else:
        feedback = destination.reviews.aggregate(review_count=Count('id'), average_rating=Avg('rating'))
        review_count = feedback['review_count']
        average_rating = feedback['average_rating']
    return {
        'id': destination.id,
        'name': destination.name,
        'description': destination.description,
        'category': destination.category,
        'interests': destination.interests,
        'address': destination.address,
        'coordinates': [float(destination.latitude), float(destination.longitude)],
        'hours': f'{display_time(destination.opening_time)} - {display_time(destination.closing_time)}',
        'opening_time': destination.opening_time.strftime('%H:%M'),
        'closing_time': destination.closing_time.strftime('%H:%M'),
        'operating_days': destination.operating_days,
        'availability_start': destination.availability_start.isoformat() if destination.availability_start else '',
        'availability_end': destination.availability_end.isoformat() if destination.availability_end else '',
        'visit_minutes': destination.visit_minutes,
        'entrance_fee': float(destination.entrance_fee),
        'activities': destination.activities,
        'accessibility': destination.accessibility,
        'contact_information': destination.contact_information,
        'image_url': uploaded_image_url or destination.image_url,
        'external_image_url': destination.image_url,
        'has_uploaded_image': bool(uploaded_image_url),
        'transportation_options': destination.transportation_options,
        'safety_reminders': destination.safety_reminders,
        'recommended_companions': destination.recommended_companions,
        'advisory': destination.advisory,
        'area': destination.area,
        'is_active': destination.is_active,
        'is_verified': destination.is_verified,
        'review_count': review_count,
        'average_rating': round(float(average_rating), 1) if average_rating is not None else None,
    }


def site_settings_payload(settings_record):
    logo_url = settings_record.logo.url if settings_record.logo else ''
    return {
        'site_name': settings_record.site_name,
        'tagline': settings_record.tagline,
        'organization_name': settings_record.organization_name,
        'municipality_name': settings_record.municipality_name,
        'support_email': settings_record.support_email,
        'support_phone': settings_record.support_phone,
        'logo_url': logo_url,
        'has_logo': bool(logo_url),
        'updated_at': settings_record.updated_at.isoformat() if settings_record.updated_at else None,
    }


def read_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return None


def valid_destination_image(upload):
    header = upload.read(12)
    upload.seek(0)
    return (
        header.startswith(b'\xff\xd8\xff')
        or header.startswith(b'\x89PNG\r\n\x1a\n')
        or (header.startswith(b'RIFF') and header[8:12] == b'WEBP')
    )


def user_payload(user):
    if not user.is_authenticated:
        return {'is_authenticated': False, 'role': 'guest'}
    payload = {
        'is_authenticated': True,
        'username': user.get_username(),
        'email': user.email,
        'display_name': user.first_name or user.get_username(),
        'role': 'admin' if user.is_staff else 'tourist',
    }
    if not user.is_staff:
        try:
            payload['preferences_completed'] = user.tourist_profile.onboarding_completed
        except TouristProfile.DoesNotExist:
            payload['preferences_completed'] = False
    return payload


def profile_payload(user):
    profile, _ = TouristProfile.objects.get_or_create(
        user=user,
        defaults={'display_name': user.first_name or user.get_username()},
    )
    recent_itineraries = SavedItinerary.objects.filter(owner=user)[:5]
    return {
        'full_name': profile.display_name or user.first_name,
        'username': user.get_username(),
        'email': user.email,
        'home_location': profile.home_location,
        'bio': profile.bio,
        'interests': profile.interests,
        'preferred_categories': profile.preferred_categories,
        'budget_min': float(profile.budget_min) if profile.budget_min is not None else '',
        'budget_max': float(profile.budget_max) if profile.budget_max is not None else '',
        'available_start_time': profile.available_start_time.strftime('%H:%M'),
        'available_end_time': profile.available_end_time.strftime('%H:%M'),
        'preferred_pace': profile.preferred_pace,
        'preferred_transportation': profile.preferred_transportation,
        'traveler_type': profile.traveler_type,
        'preferred_language': profile.preferred_language,
        'accessibility_needs': profile.accessibility_needs,
        'starting_location': profile.starting_location,
        'latitude': float(profile.latitude) if profile.latitude is not None else '',
        'longitude': float(profile.longitude) if profile.longitude is not None else '',
        'onboarding_completed': profile.onboarding_completed,
        'typical_budget': float(profile.typical_budget) if profile.typical_budget is not None else '',
        'saved_itinerary_count': SavedItinerary.objects.filter(owner=user).count(),
        'review_count': DestinationReview.objects.filter(author=user).count(),
        'recent_itineraries': [
            {
                'id': itinerary.id,
                'name': itinerary.name,
                'travel_date': itinerary.travel_date.isoformat(),
                'updated_at': itinerary.updated_at.isoformat(),
            }
            for itinerary in recent_itineraries
        ],
    }


def preference_payload(profile):
    return {
        'selected_interests': profile.interests,
        'preferred_categories': profile.preferred_categories,
        'budget_min': float(profile.budget_min) if profile.budget_min is not None else '',
        'budget_max': float(profile.budget_max) if profile.budget_max is not None else '',
        'available_start_time': profile.available_start_time.strftime('%H:%M'),
        'available_end_time': profile.available_end_time.strftime('%H:%M'),
        'travel_pace': profile.preferred_pace,
        'transportation_preference': profile.preferred_transportation,
        'traveler_type': profile.traveler_type,
        'accessibility_requirements': profile.accessibility_needs,
        'preferred_language': profile.preferred_language,
        'starting_location': profile.starting_location,
        'latitude': float(profile.latitude) if profile.latitude is not None else '',
        'longitude': float(profile.longitude) if profile.longitude is not None else '',
        'onboarding_completed': profile.onboarding_completed,
        'created_at': profile.created_at.isoformat() if profile.created_at else None,
        'updated_at': profile.updated_at.isoformat(),
    }


def review_author_name(review):
    try:
        profile_name = review.author.tourist_profile.display_name
    except TouristProfile.DoesNotExist:
        profile_name = ''
    return profile_name or review.author.first_name or review.author.get_username()


def destination_feedback_payload(destination, user):
    reviews = DestinationReview.objects.filter(destination=destination).select_related('author', 'author__tourist_profile')
    summary = reviews.aggregate(average_rating=Avg('rating'), review_count=Count('id'))
    public_reviews = [
        {
            'id': review.id,
            'author': review_author_name(review),
            'rating': review.rating,
            'comment': review.comment,
            'updated_at': review.updated_at.isoformat(),
        }
        for review in reviews.exclude(comment='')[:30]
    ]
    own_review = None
    if user.is_authenticated:
        review = reviews.filter(author=user).first()
        if review:
            own_review = {
                'rating': review.rating,
                'comment': review.comment,
                'suggestion': review.suggestion,
                'updated_at': review.updated_at.isoformat(),
            }
    return {
        'destination': {'id': destination.id, 'name': destination.name},
        'average_rating': round(float(summary['average_rating']), 1) if summary['average_rating'] is not None else None,
        'review_count': summary['review_count'],
        'reviews': public_reviews,
        'own_review': own_review,
    }


def authenticate_identifier(request, identifier, password):
    """Authenticate a username first, then a unique matching email address."""
    User = get_user_model()
    username_field = User.USERNAME_FIELD

    username_record = User.objects.filter(
        **{f'{username_field}__iexact': identifier},
    ).first()
    if username_record:
        user = authenticate(request, username=username_record.get_username(), password=password)
        if user is not None:
            return user, False

    email_records = User.objects.filter(
        Q(email__iexact=identifier) & ~Q(email=''),
    )
    authenticated_users = []
    for record in email_records:
        if username_record and record.pk == username_record.pk:
            continue
        user = authenticate(request, username=record.get_username(), password=password)
        if user is not None:
            authenticated_users.append(user)
            if len(authenticated_users) > 1:
                return None, True

    return (authenticated_users[0], False) if authenticated_users else (None, False)


def staff_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Sign in is required.'}, status=401)
        if not request.user.is_staff:
            return JsonResponse({'error': 'Administrator permission is required.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


def tourist_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Sign in is required.'}, status=401)
        if request.user.is_staff:
            return JsonResponse({'error': 'Tourist preferences are available to traveler accounts.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


def validation_error_response(error):
    messages = getattr(error, 'message_dict', {'detail': error.messages})
    field_errors = {
        field: [str(message) for message in field_messages]
        for field, field_messages in messages.items()
    }
    return JsonResponse({'error': 'Review the highlighted destination details.', 'fields': field_errors}, status=400)


def request_validation_response(errors, message='The itinerary could not be generated.'):
    return JsonResponse({'success': False, 'message': message, 'errors': errors}, status=400)


def parse_time(value):
    try:
        return datetime.strptime(value, '%H:%M')
    except (TypeError, ValueError):
        return None


def validate_tourist_preferences(data):
    allowed_fields = {
        'selected_interests', 'preferred_categories', 'budget_min', 'budget_max',
        'available_start_time', 'available_end_time', 'travel_pace',
        'transportation_preference', 'traveler_type', 'accessibility_requirements',
        'preferred_language', 'starting_location', 'latitude', 'longitude',
    }
    if not isinstance(data, dict):
        return None, {'request': ['Provide valid preference details.']}
    if set(data).difference(allowed_fields):
        return None, {'request': ['Unexpected preference fields are not allowed.']}

    errors = {}
    interests = data.get('selected_interests', [])
    categories = data.get('preferred_categories', [])
    if not isinstance(interests, list) or not interests:
        errors['selected_interests'] = ['Choose at least one travel interest.']
    elif any(item not in SUPPORTED_INTERESTS for item in interests):
        errors['selected_interests'] = ['Choose interests from the available list.']
    elif len(interests) != len(set(interests)):
        errors['selected_interests'] = ['Duplicate interests are not allowed.']
    if not isinstance(categories, list) or not categories:
        errors['preferred_categories'] = ['Choose at least one tourism category.']
    elif any(item not in SUPPORTED_CATEGORIES for item in categories):
        errors['preferred_categories'] = ['Choose categories from the available list.']
    elif len(categories) != len(set(categories)):
        errors['preferred_categories'] = ['Duplicate categories are not allowed.']

    parsed_budget = {}
    for field in ('budget_min', 'budget_max'):
        value = data.get(field)
        if value in (None, ''):
            errors[field] = ['Enter your preferred budget range.']
            continue
        try:
            parsed_budget[field] = Decimal(str(value))
            if parsed_budget[field] < 0 or parsed_budget[field] > Decimal('99999999.99'):
                errors[field] = ['Enter an amount from ₱0 to ₱99,999,999.99.']
        except (InvalidOperation, TypeError, ValueError):
            errors[field] = ['Enter a valid budget amount.']
    if not errors.get('budget_min') and not errors.get('budget_max') and parsed_budget['budget_min'] > parsed_budget['budget_max']:
        errors['budget_max'] = ['Maximum budget must be greater than or equal to minimum budget.']

    start_time = parse_time(data.get('available_start_time'))
    end_time = parse_time(data.get('available_end_time'))
    if not start_time:
        errors['available_start_time'] = ['Choose when your available travel time starts.']
    if not end_time:
        errors['available_end_time'] = ['Choose when your available travel time ends.']
    if start_time and end_time and start_time >= end_time:
        errors['available_end_time'] = ['Available end time must be later than the start time.']

    pace = data.get('travel_pace')
    transportation = data.get('transportation_preference')
    traveler_type = data.get('traveler_type')
    language = data.get('preferred_language')
    if pace not in SUPPORTED_PACES:
        errors['travel_pace'] = ['Choose a supported travel pace.']
    if transportation not in SUPPORTED_TRANSPORT:
        errors['transportation_preference'] = ['Choose a supported transportation option.']
    if traveler_type not in SUPPORTED_TRAVELER_TYPES:
        errors['traveler_type'] = ['Choose who you normally travel with.']
    if language not in SUPPORTED_LANGUAGES:
        errors['preferred_language'] = ['Choose English, Filipino, or Cebuano.']

    accessibility = strip_tags(str(data.get('accessibility_requirements') or '')).strip()
    starting_location = strip_tags(str(data.get('starting_location') or '')).strip()
    if len(accessibility) > 255:
        errors['accessibility_requirements'] = ['Accessibility requirements must be 255 characters or fewer.']
    if len(starting_location) > 255:
        errors['starting_location'] = ['Starting location must be 255 characters or fewer.']

    coordinates = {}
    for field, minimum, maximum in (('latitude', -90, 90), ('longitude', -180, 180)):
        value = data.get(field)
        if value in (None, ''):
            coordinates[field] = None
            continue
        try:
            coordinates[field] = Decimal(str(value))
            if not Decimal(str(minimum)) <= coordinates[field] <= Decimal(str(maximum)):
                errors[field] = [f'{field.title()} must be between {minimum} and {maximum}.']
        except (InvalidOperation, TypeError, ValueError):
            errors[field] = [f'Enter a valid {field}.']
    if (coordinates.get('latitude') is None) != (coordinates.get('longitude') is None):
        errors['coordinates'] = ['Latitude and longitude must be provided together.']

    if errors:
        return None, errors
    return {
        'interests': interests,
        'preferred_categories': categories,
        **parsed_budget,
        'available_start_time': start_time.time(),
        'available_end_time': end_time.time(),
        'preferred_pace': pace,
        'preferred_transportation': transportation,
        'traveler_type': traveler_type,
        'accessibility_needs': accessibility,
        'preferred_language': language,
        'starting_location': starting_location,
        **coordinates,
    }, {}


def validate_itinerary_request(data):
    if not isinstance(data, dict):
        return {'request': ['The request body must be a JSON object.']}

    allowed_fields = {
        'travel_date', 'starting_location', 'start_time', 'end_time', 'travel_days', 'travelers',
        'companion', 'interests', 'preferred_destinations', 'excluded_destinations', 'budget',
        'transportation', 'pace', 'accessibility', 'language',
    }
    errors = {}
    unexpected = set(data).difference(allowed_fields)
    if unexpected:
        errors['request'] = ['Unexpected fields are not allowed.']

    travel_date = data.get('travel_date')
    parsed_date = None
    try:
        parsed_date = date.fromisoformat(travel_date)
        if parsed_date < timezone.localdate():
            errors['travel_date'] = ['Travel date cannot be in the past.']
    except (TypeError, ValueError):
        errors['travel_date'] = ['Provide a valid travel date.']

    starting_location = data.get('starting_location', '')
    if not isinstance(starting_location, str) or not starting_location.strip():
        errors['starting_location'] = ['Starting location is required.']
    elif len(starting_location) > MAX_TEXT_LENGTH:
        errors['starting_location'] = ['Starting location is too long.']

    start = parse_time(data.get('start_time'))
    end = parse_time(data.get('end_time'))
    if start is None:
        errors['start_time'] = ['Provide a valid start time.']
    if end is None:
        errors['end_time'] = ['Provide a valid end time.']
    if start and end and end <= start:
        errors['end_time'] = ['The end time must be later than the start time.']

    try:
        travel_days = int(data.get('travel_days', 1))
        if travel_days != 1:
            errors['travel_days'] = ['The configured fallback scheduler currently supports one-day trips only.']
    except (TypeError, ValueError):
        errors['travel_days'] = ['Travel days must be a whole number.']

    try:
        travelers = int(data.get('travelers', 1))
        if not 1 <= travelers <= MAX_TRAVELERS:
            errors['travelers'] = [f'Travelers must be between 1 and {MAX_TRAVELERS}.']
    except (TypeError, ValueError):
        errors['travelers'] = ['Travelers must be a whole number.']

    interests = data.get('interests')
    if not isinstance(interests, list) or not interests or not all(isinstance(item, str) and item.strip() for item in interests):
        errors['interests'] = ['Select at least one valid travel interest.']
    elif len(interests) != len(set(interests)):
        errors['interests'] = ['Duplicate interests are not allowed.']

    for field in ('preferred_destinations', 'excluded_destinations'):
        values = data.get(field, [])
        if not isinstance(values, list):
            errors[field] = ['Destination IDs must be provided as a list.']
            continue
        if len(values) != len(set(values)):
            errors[field] = ['Duplicate destination IDs are not allowed.']
            continue
        if not all(isinstance(item, int) and item > 0 for item in values):
            errors[field] = ['Destination IDs must be positive integers.']

    preferred_values = data.get('preferred_destinations') if isinstance(data.get('preferred_destinations'), list) else []
    excluded_values = data.get('excluded_destinations') if isinstance(data.get('excluded_destinations'), list) else []
    selected_ids = preferred_values + excluded_values
    if isinstance(selected_ids, list) and selected_ids and all(isinstance(item, int) for item in selected_ids):
        destinations = {item.id: item for item in Destination.objects.filter(id__in=selected_ids)}
        unknown = set(selected_ids).difference(destinations)
        if unknown:
            errors['preferred_destinations'] = ['One or more selected destinations do not exist.']
        unavailable = [item for item in data.get('preferred_destinations', []) if item in destinations and (not destinations[item].is_active or not destinations[item].is_verified)]
        if unavailable:
            errors['preferred_destinations'] = ['Selected destinations must be active and verified.']
        seasonally_unavailable = [item for item in data.get('preferred_destinations', []) if item in destinations and parsed_date and not destination_available_on(destinations[item], parsed_date)]
        if seasonally_unavailable:
            errors['preferred_destinations'] = ['One or more selected destinations are unavailable on the chosen travel date.']

    try:
        budget = Decimal(str(data.get('budget') or 0))
        if budget < 0:
            errors['budget'] = ['Budget cannot be negative.']
    except (InvalidOperation, TypeError, ValueError):
        errors['budget'] = ['Budget must be a valid amount.']

    if data.get('transportation') not in SUPPORTED_TRANSPORT:
        errors['transportation'] = ['Select a supported transportation preference.']
    if data.get('pace') not in SUPPORTED_PACES:
        errors['pace'] = ['Select a supported travel pace.']
    if data.get('language') not in SUPPORTED_LANGUAGES:
        errors['language'] = ['Select English, Filipino, or Cebuano.']
    if len(str(data.get('accessibility', ''))) > MAX_TEXT_LENGTH:
        errors['accessibility'] = ['Accessibility requirements are too long.']
    return errors


def parse_clock(value, default):
    try:
        return datetime.strptime(value or default, '%H:%M')
    except ValueError:
        return datetime.strptime(default, '%H:%M')


def format_clock(moment):
    return display_time(moment)


def travel_minutes(previous, current, transport):
    if previous is None:
        return 25 if transport != 'walking' else 50
    if previous.area == current.area:
        return 18 if transport != 'walking' else 40
    return 35 if transport != 'walking' else 75


def build_schedule(data, user=None):
    selected_order = list(data.get('preferred_destinations', []))
    selected_ids = set(selected_order)
    excluded_ids = set(data.get('excluded_destinations', []))
    needs_accessibility = bool(data.get('accessibility'))
    budget = Decimal(str(data.get('budget') or 0))
    travelers = int(data.get('travelers') or 1)
    transport = data.get('transportation', 'public')
    pace = data.get('pace', 'balanced')
    start = parse_clock(data.get('start_time'), '08:00')
    end = parse_clock(data.get('end_time'), '17:00')
    trip_date = date.fromisoformat(data['travel_date'])
    trip_day = trip_date.strftime('%A')
    available = [
        item for item in Destination.objects.filter(is_active=True, is_verified=True)
        .exclude(id__in=excluded_ids).annotate(average_rating=Avg('reviews__rating'), review_count=Count('reviews'))
        if trip_day in item.operating_days and destination_available_on(item, trip_date)
    ]
    recommender = HybridRecommendationEngine(data, user=user)
    ranked = recommender.rank(available)
    if not ranked:
        return None

    stops = []
    cursor = start
    previous = None
    included_ids = set()
    destination_cost = Decimal('0')
    lunch_added = False
    pace_factor = PACE_FACTORS.get(pace, 1)
    for recommendation in ranked:
        destination = recommendation.destination
        transfer = travel_minutes(previous, destination, transport)
        arrival = cursor + timedelta(minutes=transfer)
        open_at = datetime.combine(arrival.date(), destination.opening_time)
        close_at = datetime.combine(arrival.date(), destination.closing_time)
        if arrival < open_at:
            arrival = open_at
        duration = int(destination.visit_minutes * pace_factor)
        departure = arrival + timedelta(minutes=duration)
        if departure > close_at or departure + timedelta(minutes=35) > end:
            continue
        if previous:
            stops.append({
                'type': 'travel',
                'title': f'Travel to {destination.name}',
                'start': format_clock(cursor),
                'end': format_clock(arrival),
                'duration_minutes': int((arrival - cursor).total_seconds() / 60),
                'transportation': transport,
                'description': 'Estimated transfer time. Conditions may change.',
            })
        if not lunch_added and arrival.hour >= 11:
            lunch_end = arrival + timedelta(minutes=50)
            if lunch_end + timedelta(minutes=duration) <= close_at and lunch_end <= end:
                stops.append({
                    'type': 'meal',
                    'title': 'Lunch break',
                    'start': format_clock(arrival),
                    'end': format_clock(lunch_end),
                    'duration_minutes': 50,
                    'description': 'Set aside time for a nearby local meal.',
                    'estimated_cost': None,
                })
                arrival = lunch_end
                departure = arrival + timedelta(minutes=duration)
                lunch_added = True
        stops.append({
            'type': 'destination',
            'id': destination.id,
            'title': destination.name,
            'start': format_clock(arrival),
            'end': format_clock(departure),
            'duration_minutes': duration,
            'description': destination.description,
            'address': destination.address,
            'image_url': destination.image_url,
            'activities': destination.activities,
            'accessibility': destination.accessibility or 'Accessibility details currently unavailable.',
            'estimated_cost': float(destination.entrance_fee),
            'average_rating': round(float(destination.average_rating), 1) if destination.average_rating is not None else None,
            'review_count': destination.review_count,
            'safety_reminders': destination.safety_reminders,
            'coordinates': [float(destination.latitude), float(destination.longitude)],
            'recommendation': recommendation.payload(),
        })
        included_ids.add(destination.id)
        destination_cost += destination.entrance_fee * travelers
        cursor = departure
        previous = destination
        if len(included_ids) >= (4 if pace == 'fast' else 3 if pace == 'balanced' else 2):
            break

    if not stops:
        return {'error': 'The available travel time is not sufficient for all selected destinations. Remove a destination, extend your travel time, or allow the system to recommend a shorter itinerary.'}

    return_travel = 25 if transport != 'walking' else 50
    return_end = min(cursor + timedelta(minutes=return_travel), end)
    stops.append({
        'type': 'return',
        'title': 'Return to starting location',
        'start': format_clock(cursor),
        'end': format_clock(return_end),
        'duration_minutes': int((return_end - cursor).total_seconds() / 60),
        'transportation': transport,
        'description': 'Estimated return time. Conditions may change.',
    })
    total = destination_cost
    alternatives = [
        {**destination_payload(item.destination), 'recommendation': item.payload()}
        for item in ranked if item.destination.id not in included_ids
    ][:3]
    adjustments = []
    if selected_ids - included_ids:
        adjustments.append('Some selected destinations did not fit the available time or operating schedule. Similar verified alternatives are shown below.')
    if budget and total > budget:
        adjustments.append('Known entrance fees exceed your selected budget. Transport and meal prices are unavailable and not included.')
    if needs_accessibility:
        adjustments.append('Accessibility details are highlighted per stop. Please confirm support with the tourism office before traveling.')

    return {
        'title': f"{data.get('travel_date') or 'Upcoming'} {pace.title()} escape",
        'day': {'label': 'Day 1', 'date': data.get('travel_date')},
        'stops': stops,
        'alternatives': alternatives,
        'adjustments': adjustments,
        'budget': {
            'entrance_fees': float(destination_cost),
            'transportation': None,
            'food_and_drinks': None,
            'emergency_allowance': None,
            'total': float(total),
            'notice': 'Only entrance fees with verified database values are included. Transport, meals, and emergency allowance are currently unavailable.',
        },
        'map': [stop for stop in stops if stop['type'] == 'destination'],
        'summary': {
            'destinations': len(included_ids),
            'travel_minutes': sum(stop['duration_minutes'] for stop in stops if stop['type'] in ['travel', 'return']),
            'pace': pace,
            'recommendation_engine': recommender.metadata(),
        },
    }


@require_GET
def health(request):
    try:
        connection.ensure_connection()
        database_status = 'connected'
    except Exception:
        logger.exception('health_check_database_failure')
        database_status = 'unavailable'
    return JsonResponse({
        'status': 'healthy' if database_status == 'connected' else 'degraded',
        'database': database_status,
        'itinerary_service': 'hybrid_recommender',
        'recommendation_model': 'content_collaborative_contextual',
        'map_service': 'google_maps_embed',
        'version': '1.1.0',
    }, status=200 if database_status == 'connected' else 503)


@require_GET
def public_settings(request):
    return JsonResponse({'settings': site_settings_payload(SiteSettings.load())})


@require_GET
def destination_list(request):
    destinations = Destination.objects.filter(is_active=True, is_verified=True).annotate(
        average_rating=Avg('reviews__rating'), review_count=Count('reviews'),
    )
    return JsonResponse({'destinations': [destination_payload(item) for item in destinations]})


@ensure_csrf_cookie
@require_GET
def csrf(request):
    return JsonResponse({'detail': 'CSRF cookie set.'})


@require_GET
def current_user(request):
    return JsonResponse({'user': user_payload(request.user)})


@require_POST
def signup_view(request):
    data = read_body(request)
    if not isinstance(data, dict):
        return JsonResponse({'error': 'Provide valid account details.'}, status=400)

    full_name = str(data.get('full_name') or '').strip()
    username = str(data.get('username') or '').strip()
    email = str(data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    password_confirm = data.get('password_confirm') or ''
    errors = {}
    User = get_user_model()

    if len(full_name) < 2 or len(full_name) > 120:
        errors['full_name'] = ['Enter your full name using 2 to 120 characters.']
    if len(username) < 3 or len(username) > 150:
        errors['username'] = ['Choose a username using 3 to 150 characters.']
    elif User.objects.filter(username__iexact=username).exists():
        errors['username'] = ['That username is already in use.']
    try:
        validate_email(email)
    except ValidationError:
        errors['email'] = ['Enter a valid email address.']
    if email and User.objects.filter(email__iexact=email).exists():
        errors['email'] = ['An account already uses that email address.']
    if password != password_confirm:
        errors['password_confirm'] = ['Passwords do not match.']

    candidate = User(username=username, email=email, first_name=full_name)
    try:
        candidate.full_clean(exclude=['password'])
    except ValidationError as error:
        for field, messages in error.message_dict.items():
            errors.setdefault(field, []).extend(str(message) for message in messages)
    try:
        password_validation.validate_password(password, candidate)
    except ValidationError as error:
        errors['password'] = [str(message) for message in error.messages]

    if errors:
        return JsonResponse({'error': 'Review the highlighted account details.', 'errors': errors}, status=400)

    with transaction.atomic():
        candidate.set_password(password)
        candidate.save()
        TouristProfile.objects.create(user=candidate, display_name=full_name)
    login(request, candidate)
    return JsonResponse({'user': user_payload(candidate), 'profile': profile_payload(candidate)}, status=201)


@require_POST
def login_view(request):
    data = read_body(request)
    if not data:
        return JsonResponse({'error': 'Username or email and password are required.'}, status=400)
    identifier = str(data.get('identifier') or data.get('email') or '').strip()
    password = data.get('password', '')
    if not identifier or not password:
        return JsonResponse({'error': 'Username or email and password are required.'}, status=400)
    user, ambiguous_email = authenticate_identifier(request, identifier, password)
    if ambiguous_email:
        return JsonResponse({
            'error': 'More than one account uses that email. Sign in with your username instead.',
        }, status=409)
    if user is None:
        return JsonResponse({'error': 'Invalid username/email or password.'}, status=401)
    login(request, user)
    return JsonResponse({'user': user_payload(user)})


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({'user': user_payload(request.user)})


@require_http_methods(['GET', 'PATCH'])
def tourist_profile(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Sign in is required to access your profile.'}, status=401)
    if request.user.is_staff:
        return JsonResponse({'error': 'Tourist profile settings are available to traveler accounts.'}, status=403)
    if request.method == 'GET':
        return JsonResponse({'profile': profile_payload(request.user)})

    data = read_body(request)
    if not isinstance(data, dict):
        return JsonResponse({'error': 'Provide valid profile details.'}, status=400)
    allowed_fields = {
        'full_name', 'email', 'home_location', 'bio', 'interests', 'preferred_pace',
        'preferred_transportation', 'preferred_language', 'accessibility_needs', 'typical_budget',
    }
    if set(data).difference(allowed_fields):
        return JsonResponse({'error': 'Unexpected profile fields are not allowed.'}, status=400)

    errors = {}
    full_name = str(data.get('full_name', '')).strip()
    email = str(data.get('email', '')).strip().lower()
    home_location = str(data.get('home_location', '')).strip()
    bio = str(data.get('bio', '')).strip()
    accessibility = str(data.get('accessibility_needs', '')).strip()
    interests = data.get('interests', [])
    pace = data.get('preferred_pace', 'balanced')
    transportation = data.get('preferred_transportation', 'public')
    language = data.get('preferred_language', 'English')

    if len(full_name) < 2 or len(full_name) > 120:
        errors['full_name'] = ['Enter your full name using 2 to 120 characters.']
    try:
        validate_email(email)
    except ValidationError:
        errors['email'] = ['Enter a valid email address.']
    if email and get_user_model().objects.filter(email__iexact=email).exclude(pk=request.user.pk).exists():
        errors['email'] = ['An account already uses that email address.']
    if len(home_location) > 180:
        errors['home_location'] = ['Home location must be 180 characters or fewer.']
    if len(bio) > 500:
        errors['bio'] = ['About you must be 500 characters or fewer.']
    if len(accessibility) > 255:
        errors['accessibility_needs'] = ['Accessibility needs must be 255 characters or fewer.']
    if not isinstance(interests, list) or any(item not in SUPPORTED_INTERESTS for item in interests):
        errors['interests'] = ['Choose interests from the available travel interest list.']
    elif len(interests) != len(set(interests)):
        errors['interests'] = ['Duplicate interests are not allowed.']
    if pace not in SUPPORTED_PACES:
        errors['preferred_pace'] = ['Choose a supported travel pace.']
    if transportation not in SUPPORTED_TRANSPORT:
        errors['preferred_transportation'] = ['Choose a supported transportation option.']
    if language not in SUPPORTED_LANGUAGES:
        errors['preferred_language'] = ['Choose English, Filipino, or Cebuano.']

    budget = data.get('typical_budget')
    parsed_budget = None
    if budget not in (None, ''):
        try:
            parsed_budget = Decimal(str(budget))
            if parsed_budget < 0 or parsed_budget > Decimal('99999999.99'):
                errors['typical_budget'] = ['Enter a budget from ₱0 to ₱99,999,999.99.']
        except (InvalidOperation, TypeError, ValueError):
            errors['typical_budget'] = ['Enter a valid budget amount.']
    if errors:
        return JsonResponse({'error': 'Review the highlighted profile details.', 'errors': errors}, status=400)

    profile, _ = TouristProfile.objects.get_or_create(user=request.user)
    profile.display_name = full_name
    profile.home_location = home_location
    profile.bio = bio
    profile.interests = interests
    profile.preferred_pace = pace
    profile.preferred_transportation = transportation
    profile.preferred_language = language
    profile.accessibility_needs = accessibility
    profile.typical_budget = parsed_budget
    with transaction.atomic():
        request.user.first_name = full_name
        request.user.email = email
        request.user.save(update_fields=['first_name', 'email'])
        profile.full_clean()
        profile.save()
    return JsonResponse({'user': user_payload(request.user), 'profile': profile_payload(request.user)})


@require_http_methods(['GET', 'POST', 'PUT'])
@tourist_required
def tourist_preferences(request):
    profile, _ = TouristProfile.objects.get_or_create(
        user=request.user,
        defaults={'display_name': request.user.first_name or request.user.get_username()},
    )
    if request.method == 'GET':
        return JsonResponse({
            'success': True,
            'preferences': preference_payload(profile),
            'onboarding_required': not profile.onboarding_completed,
        })

    cleaned, errors = validate_tourist_preferences(read_body(request))
    if errors:
        return JsonResponse({
            'success': False,
            'error': 'Complete the required travel preferences before continuing.',
            'errors': errors,
        }, status=400)

    for field, value in cleaned.items():
        setattr(profile, field, value)
    profile.typical_budget = cleaned['budget_max']
    if cleaned['starting_location']:
        profile.home_location = cleaned['starting_location']
    profile.onboarding_completed = True
    try:
        profile.full_clean()
        profile.save()
    except ValidationError as error:
        messages = getattr(error, 'message_dict', {'detail': error.messages})
        return JsonResponse({
            'success': False,
            'error': 'Review the highlighted preferences.',
            'errors': {field: [str(message) for message in values] for field, values in messages.items()},
        }, status=400)
    return JsonResponse({
        'success': True,
        'message': 'Travel preferences saved.',
        'preferences': preference_payload(profile),
        'user': user_payload(request.user),
    })


def recommendation_tier(index, score):
    if index == 0:
        return 'Best Match'
    if score is not None and score >= 70:
        return 'Highly Recommended'
    return 'Other Matching Destinations'


def tourist_recommendation_response(request):
    profile, _ = TouristProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_completed:
        return JsonResponse({
            'success': False,
            'onboarding_required': True,
            'error': 'Complete your travel preferences to view personalized recommendations.',
        }, status=409)

    today = timezone.localdate()
    eligible_destinations = list(Destination.objects.filter(
        is_active=True,
        is_verified=True,
    ).filter(
        Q(availability_start__isnull=True) | Q(availability_start__lte=today),
        Q(availability_end__isnull=True) | Q(availability_end__gte=today),
    ).annotate(
        average_rating=Avg('reviews__rating'), review_count=Count('reviews'),
    ))
    destination_map = {destination.id: destination for destination in eligible_destinations}
    fallback = False
    fallback_message = ''
    invalid_recommendation_count = 0

    try:
        ranked_references, metadata = build_preference_recommendations(
            profile, eligible_destinations, user=request.user,
        )
    except Exception:
        logger.exception('tourist_recommendation_service_failure user_id=%s', request.user.pk)
        fallback = True
        fallback_message = 'Personalized recommendations are temporarily unavailable. Popular tourist destinations are shown instead.'
        metadata = {
            'name': 'popular-destinations-fallback',
            'strategy': 'verified destination ratings and popularity',
            'collaborative_enabled': False,
        }
        popular_destinations = sorted(
            eligible_destinations,
            key=lambda item: (-(float(item.average_rating) if item.average_rating is not None else 0), -item.review_count, item.name.casefold()),
        )
        ranked_references = [{
            'destination_id': destination.id,
            'match_score': None,
            'recommendation_reason': 'Popular with travelers and verified by the local tourism office.',
            'estimated_travel_minutes': None,
            'estimated_travel_time': 'Estimate unavailable',
            'distance_km': None,
            'signals': {},
        } for destination in popular_destinations]

    recommendations = []
    included_ids = set()
    for reference in ranked_references:
        destination_id = reference.get('destination_id') if isinstance(reference, dict) else None
        destination = destination_map.get(destination_id)
        if destination is None or destination_id in included_ids:
            invalid_recommendation_count += 1
            continue
        included_ids.add(destination_id)
        score = reference.get('match_score')
        item = destination_payload(destination)
        item.update({
            'destination_id': destination.id,
            'destination_name': destination.name,
            'match_score': score,
            'recommendation_reason': reference.get('recommendation_reason') or 'Matches your saved travel preferences.',
            'estimated_travel_minutes': reference.get('estimated_travel_minutes'),
            'estimated_travel_time': reference.get('estimated_travel_time') or 'Estimate unavailable',
            'distance_km': reference.get('distance_km'),
            'signals': reference.get('signals') or {},
            'match_tier': recommendation_tier(len(recommendations), score),
            'accessibility_information': destination.accessibility or 'Information unavailable',
            'tourism_office_recommended': destination.is_verified,
            'has_incomplete_information': not all([
                destination.address, destination.opening_time, destination.closing_time,
                destination.accessibility, destination.transportation_options,
            ]),
        })
        recommendations.append(item)

    empty_message = ''
    if not recommendations:
        empty_message = 'No tourist destinations currently match all your selected preferences. Try changing your interests, available time, location, or budget.'
    data_warning = ''
    if any(item['has_incomplete_information'] for item in recommendations):
        data_warning = 'Some destination information is currently unavailable. Please confirm the details with the local tourism office before traveling.'
    return JsonResponse({
        'success': True,
        'personalized': not fallback,
        'fallback': fallback,
        'message': fallback_message or empty_message,
        'data_warning': data_warning,
        'preferences': preference_payload(profile),
        'recommendations': recommendations,
        'recommendation_groups': ['Best Match', 'Highly Recommended', 'Other Matching Destinations'],
        'engine': metadata,
        'invalid_recommendation_count': invalid_recommendation_count,
    })


@require_GET
@tourist_required
def tourist_recommendations(request):
    return tourist_recommendation_response(request)


@require_POST
@tourist_required
def generate_tourist_recommendations(request):
    return tourist_recommendation_response(request)


@require_http_methods(['GET', 'POST'])
def destination_feedback(request, destination_id):
    try:
        destination = Destination.objects.get(pk=destination_id, is_active=True, is_verified=True)
    except Destination.DoesNotExist:
        return JsonResponse({'error': 'Destination not found.'}, status=404)

    if request.method == 'GET':
        return JsonResponse(destination_feedback_payload(destination, request.user))
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Sign in as a tourist to rate this destination.'}, status=401)
    if request.user.is_staff:
        return JsonResponse({'error': 'Destination feedback is available to traveler accounts.'}, status=403)

    data = read_body(request)
    if not isinstance(data, dict):
        return JsonResponse({'error': 'Provide valid feedback details.'}, status=400)
    try:
        rating = int(data.get('rating'))
    except (TypeError, ValueError):
        rating = 0
    comment = str(data.get('comment') or '').strip()
    suggestion = str(data.get('suggestion') or '').strip()
    errors = {}
    if rating not in range(1, 6):
        errors['rating'] = ['Choose a rating from 1 to 5 stars.']
    if len(comment) > 1200:
        errors['comment'] = ['Your comment must be 1,200 characters or fewer.']
    if len(suggestion) > 1200:
        errors['suggestion'] = ['Your suggestion must be 1,200 characters or fewer.']
    if errors:
        return JsonResponse({'error': 'Review your destination feedback.', 'errors': errors}, status=400)

    review, _ = DestinationReview.objects.update_or_create(
        destination=destination,
        author=request.user,
        defaults={'rating': rating, 'comment': comment, 'suggestion': suggestion},
    )
    review.full_clean()
    review.save()
    return JsonResponse(destination_feedback_payload(destination, request.user), status=200)


@require_POST
def generate_itinerary(request):
    data = read_body(request)
    if data is None:
        return request_validation_response({'request': ['Invalid JSON request body.']})
    errors = validate_itinerary_request(data)
    if errors:
        return request_validation_response(errors)
    schedule = build_schedule(data, user=request.user)
    if schedule is None:
        return JsonResponse({
            'success': False,
            'message': 'No destinations currently match all your selected preferences.',
            'errors': {'destinations': ['Try changing your travel date, interests, or preferred destinations.']},
        }, status=422)
    if schedule.get('error'):
        return JsonResponse({'success': False, 'message': schedule['error'], 'errors': {'schedule': [schedule['error']]}}, status=422)
    return JsonResponse({'success': True, 'itinerary': schedule})


def saved_itineraries(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Sign in is required to access saved itineraries.'}, status=401)
    if request.method == 'GET':
        saved = SavedItinerary.objects.filter(owner=request.user)[:20]
        return JsonResponse({'itineraries': [
            {'id': item.id, 'name': item.name, 'travel_date': item.travel_date, 'updated_at': item.updated_at.isoformat()}
            for item in saved
        ]})
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)
    data = read_body(request)
    if not data or not data.get('itinerary') or not data.get('preferences'):
        return JsonResponse({'error': 'Itinerary and preferences are required.'}, status=400)
    if not data['preferences'].get('travel_date'):
        return JsonResponse({'error': 'A travel date is required to save an itinerary.'}, status=400)
    saved = SavedItinerary.objects.create(
        name=data.get('name') or data['itinerary'].get('title', 'My itinerary'),
        owner=request.user,
        travel_date=data['preferences'].get('travel_date'),
        preferences=data['preferences'],
        itinerary=data['itinerary'],
    )
    return JsonResponse({'id': saved.id, 'message': 'Itinerary saved.'}, status=201)


@require_GET
@staff_required
def admin_dashboard(request):
    destinations = Destination.objects.all()
    ready_destinations = destinations.filter(is_active=True, is_verified=True)
    pending_destinations = destinations.filter(is_active=True, is_verified=False)
    inactive_destinations = destinations.filter(is_active=False)
    interest_counts = {}
    for destination in destinations:
        for interest in destination.interests:
            interest_counts[interest] = interest_counts.get(interest, 0) + 1
    destination_count = destinations.count()
    average_fee = destinations.aggregate(value=Avg('entrance_fee'))['value']
    attention_items = []
    for destination in destinations.filter(
        Q(is_active=False) | Q(is_verified=False) | ~Q(advisory=''),
    )[:6]:
        if not destination.is_active:
            issue = 'Unavailable'
        elif not destination.is_verified:
            issue = 'Needs verification'
        else:
            issue = 'Active advisory'
        attention_items.append({
            'id': destination.id,
            'name': destination.name,
            'category': destination.category,
            'area': destination.area,
            'issue': issue,
        })
    recent_itineraries = SavedItinerary.objects.all()[:5]
    return JsonResponse({
        'stats': {
            'destinations': destination_count,
            'active_destinations': destinations.filter(is_active=True).count(),
            'verified_destinations': destinations.filter(is_verified=True).count(),
            'ready_destinations': ready_destinations.count(),
            'pending_destinations': pending_destinations.count(),
            'inactive_destinations': inactive_destinations.count(),
            'advisory_destinations': destinations.exclude(advisory='').count(),
            'saved_itineraries': SavedItinerary.objects.count(),
            'categories': destinations.order_by().values('category').distinct().count(),
            'areas': destinations.order_by().values('area').distinct().count(),
            'average_entrance_fee': float(average_fee) if average_fee is not None else None,
            'readiness_percent': round((ready_destinations.count() / destination_count) * 100) if destination_count else 0,
        },
        'popular_interests': sorted(interest_counts.items(), key=lambda item: item[1], reverse=True)[:5],
        'category_counts': list(
            destinations.values('category').annotate(count=Count('id')).order_by('-count', 'category')[:6]
        ),
        'attention_items': attention_items,
        'recent_itineraries': [
            {
                'id': itinerary.id,
                'name': itinerary.name,
                'travel_date': itinerary.travel_date.isoformat(),
                'updated_at': itinerary.updated_at.isoformat(),
            }
            for itinerary in recent_itineraries
        ],
    })


@require_GET
@staff_required
def admin_users(request):
    User = get_user_model()
    users = User.objects.annotate(
        saved_itinerary_count=Count('saved_itineraries', distinct=True),
        review_count=Count('destination_reviews', distinct=True),
    ).select_related('tourist_profile').order_by('-date_joined')
    payload = []
    for user in users:
        try:
            profile = user.tourist_profile
        except TouristProfile.DoesNotExist:
            profile = None
        payload.append({
            'id': user.id,
            'username': user.get_username(),
            'email': user.email,
            'display_name': (profile.display_name if profile else '') or user.first_name or user.get_username(),
            'role': 'admin' if user.is_staff else 'tourist',
            'is_active': user.is_active,
            'date_joined': user.date_joined.isoformat(),
            'last_login': user.last_login.isoformat() if user.last_login else None,
            'home_location': profile.home_location if profile else '',
            'interests': profile.interests if profile else [],
            'preferred_pace': profile.preferred_pace if profile else '',
            'preferred_transportation': profile.preferred_transportation if profile else '',
            'preferred_language': profile.preferred_language if profile else '',
            'saved_itinerary_count': user.saved_itinerary_count,
            'review_count': user.review_count,
        })
    return JsonResponse({'users': payload})


@require_http_methods(['GET', 'PATCH'])
@staff_required
def admin_settings(request):
    settings_record = SiteSettings.load()
    if request.method == 'GET':
        return JsonResponse({'settings': site_settings_payload(settings_record)})

    data = read_body(request)
    if not isinstance(data, dict):
        return JsonResponse({'error': 'Provide valid settings details.'}, status=400)
    allowed_fields = {
        'site_name', 'tagline', 'organization_name', 'municipality_name',
        'support_email', 'support_phone',
    }
    unexpected_fields = set(data).difference(allowed_fields)
    if unexpected_fields:
        return JsonResponse({'error': 'Unexpected settings fields are not allowed.'}, status=400)
    for field, value in data.items():
        if not isinstance(value, str):
            return JsonResponse({'error': 'Settings values must be text.'}, status=400)
        setattr(settings_record, field, value.strip())
    try:
        settings_record.full_clean()
        settings_record.save()
    except ValidationError as error:
        messages = getattr(error, 'message_dict', {'detail': error.messages})
        return JsonResponse({
            'error': 'Review the highlighted settings.',
            'fields': {field: [str(message) for message in values] for field, values in messages.items()},
        }, status=400)
    return JsonResponse({'settings': site_settings_payload(settings_record)})


@require_http_methods(['POST', 'DELETE'])
@staff_required
def admin_settings_logo(request):
    settings_record = SiteSettings.load()
    if request.method == 'DELETE':
        if settings_record.logo:
            settings_record.logo.delete(save=False)
            settings_record.logo = ''
            settings_record.save(update_fields=['logo', 'updated_at'])
        return JsonResponse({'settings': site_settings_payload(settings_record)})

    upload = request.FILES.get('logo')
    if not upload:
        return JsonResponse({'error': 'Choose a logo to upload.'}, status=400)
    if upload.size > MAX_SITE_LOGO_BYTES:
        return JsonResponse({'error': 'The logo must be 2 MB or smaller.'}, status=400)
    if upload.content_type not in DESTINATION_IMAGE_TYPES or not valid_destination_image(upload):
        return JsonResponse({'error': 'Upload a valid JPG, PNG, or WebP logo.'}, status=400)

    previous_logo = settings_record.logo
    settings_record.logo = upload
    try:
        settings_record.full_clean()
        settings_record.save(update_fields=['logo', 'updated_at'])
    except ValidationError as error:
        settings_record.logo = previous_logo
        messages = getattr(error, 'message_dict', {'detail': error.messages})
        return JsonResponse({
            'error': 'Review the uploaded logo.',
            'fields': {field: [str(message) for message in values] for field, values in messages.items()},
        }, status=400)
    if previous_logo and previous_logo.name != settings_record.logo.name:
        previous_logo.delete(save=False)
    return JsonResponse({'settings': site_settings_payload(settings_record)})


@require_http_methods(['GET', 'POST'])
@staff_required
def admin_destinations(request):
    if request.method == 'GET':
        destinations = Destination.objects.all().annotate(
            average_rating=Avg('reviews__rating'), review_count=Count('reviews'),
        )
        return JsonResponse({'destinations': [destination_payload(item) for item in destinations]})

    data = read_body(request)
    required = ['name', 'description', 'category', 'interests', 'area', 'address', 'latitude', 'longitude', 'opening_time', 'closing_time', 'operating_days', 'visit_minutes', 'entrance_fee']
    missing = [field for field in required if not data or data.get(field) in (None, '', [])]
    if missing:
        return JsonResponse({'error': 'Complete all required destination details before saving.'}, status=400)
    try:
        destination = Destination(
            name=data['name'], description=data['description'], category=data['category'],
            interests=data.get('interests', []), address=data['address'], latitude=data['latitude'], longitude=data['longitude'],
            opening_time=data['opening_time'], closing_time=data['closing_time'],
            operating_days=data['operating_days'], visit_minutes=data['visit_minutes'],
            availability_start=data.get('availability_start') or None,
            availability_end=data.get('availability_end') or None,
            entrance_fee=data['entrance_fee'], activities=data.get('activities', []),
            accessibility=data.get('accessibility', ''), contact_information=data.get('contact_information', ''),
            image_url=data.get('image_url', ''), is_active=bool(data.get('is_active', True)),
            is_verified=bool(data.get('is_verified', False)), transportation_options=data.get('transportation_options', []),
            safety_reminders=data.get('safety_reminders', []), recommended_companions=data.get('recommended_companions', []),
            advisory=data.get('advisory', ''), area=data['area'],
        )
        destination.full_clean()
        destination.save()
    except ValidationError as error:
        return validation_error_response(error)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Some destination details are invalid.'}, status=400)
    return JsonResponse({'destination': destination_payload(destination)}, status=201)


@require_http_methods(['PATCH', 'DELETE'])
@staff_required
def admin_destination_detail(request, destination_id):
    try:
        destination = Destination.objects.get(pk=destination_id)
    except Destination.DoesNotExist:
        return JsonResponse({'error': 'Destination not found.'}, status=404)

    if request.method == 'DELETE':
        deleted_name = destination.name
        if destination.image:
            destination.image.delete(save=False)
        destination.delete()
        return JsonResponse({
            'message': 'Destination deleted.',
            'id': destination_id,
            'name': deleted_name,
        })

    data = read_body(request)
    if data is None:
        return JsonResponse({'error': 'Invalid request data.'}, status=400)
    allowed_fields = {
        'name', 'description', 'category', 'interests', 'address', 'latitude', 'longitude', 'opening_time',
        'closing_time', 'operating_days', 'availability_start', 'availability_end', 'visit_minutes', 'entrance_fee', 'activities', 'accessibility',
        'contact_information', 'image_url', 'is_active', 'is_verified', 'transportation_options',
        'safety_reminders', 'recommended_companions', 'advisory', 'area',
    }
    for field, value in data.items():
        if field in allowed_fields:
            setattr(destination, field, value)
    try:
        destination.full_clean()
        destination.save()
    except ValidationError as error:
        return validation_error_response(error)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Some destination details are invalid.'}, status=400)
    return JsonResponse({'destination': destination_payload(destination)})


@require_http_methods(['POST', 'DELETE'])
@staff_required
def admin_destination_image(request, destination_id):
    try:
        destination = Destination.objects.get(pk=destination_id)
    except Destination.DoesNotExist:
        return JsonResponse({'error': 'Destination not found.'}, status=404)

    if request.method == 'DELETE':
        if destination.image:
            destination.image.delete(save=False)
            destination.image = ''
            destination.save(update_fields=['image'])
        return JsonResponse({'destination': destination_payload(destination)})

    upload = request.FILES.get('image')
    if not upload:
        return JsonResponse({'error': 'Choose an image to upload.'}, status=400)
    if upload.size > MAX_DESTINATION_IMAGE_BYTES:
        return JsonResponse({'error': 'The cover image must be 5 MB or smaller.'}, status=400)
    if upload.content_type not in DESTINATION_IMAGE_TYPES or not valid_destination_image(upload):
        return JsonResponse({'error': 'Upload a valid JPG, PNG, or WebP image.'}, status=400)

    previous_image = destination.image
    destination.image = upload
    try:
        destination.full_clean()
        destination.save(update_fields=['image'])
    except ValidationError as error:
        destination.image = previous_image
        return validation_error_response(error)
    if previous_image and previous_image.name != destination.image.name:
        previous_image.delete(save=False)
    return JsonResponse({'destination': destination_payload(destination)})

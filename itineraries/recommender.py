import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

from .models import SavedItinerary


MAX_HISTORY_SAMPLES = 500
MAX_REASON_COUNT = 3


def normalized_values(values):
    if not isinstance(values, list):
        return set()
    return {str(value).strip().lower() for value in values if str(value).strip()}


def text_tokens(value):
    return {token for token in re.findall(r'[a-z0-9]+', str(value).lower()) if len(token) > 2}


def jaccard_similarity(left, right):
    union = left | right
    return len(left & right) / len(union) if union else 0


def itinerary_destination_ids(itinerary):
    if not isinstance(itinerary, dict):
        return set()
    candidates = itinerary.get('map') or itinerary.get('stops') or []
    destination_ids = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        value = item.get('id')
        if isinstance(value, int) and value > 0:
            destination_ids.add(value)
    return destination_ids


def minutes_between(start, end):
    if not start or not end:
        return None
    try:
        start_minutes = start.hour * 60 + start.minute if hasattr(start, 'hour') else int(str(start)[:2]) * 60 + int(str(start)[3:5])
        end_minutes = end.hour * 60 + end.minute if hasattr(end, 'hour') else int(str(end)[:2]) * 60 + int(str(end)[3:5])
    except (TypeError, ValueError):
        return None
    return end_minutes - start_minutes if end_minutes > start_minutes else None


def clock_minutes(value):
    if not value:
        return None
    try:
        return value.hour * 60 + value.minute if hasattr(value, 'hour') else int(str(value)[:2]) * 60 + int(str(value)[3:5])
    except (TypeError, ValueError):
        return None


def distance_kilometers(origin_latitude, origin_longitude, destination):
    if origin_latitude in (None, '') or origin_longitude in (None, ''):
        return None
    try:
        first_latitude = radians(float(origin_latitude))
        second_latitude = radians(float(destination.latitude))
        latitude_difference = second_latitude - first_latitude
        longitude_difference = radians(float(destination.longitude) - float(origin_longitude))
    except (TypeError, ValueError):
        return None
    haversine = sin(latitude_difference / 2) ** 2 + cos(first_latitude) * cos(second_latitude) * sin(longitude_difference / 2) ** 2
    return 6371 * 2 * asin(sqrt(haversine))


def estimated_travel_minutes(distance, transportation):
    if distance is None:
        return None
    speeds = {'walking': 4.5, 'public': 24, 'motorcycle': 32, 'private': 36}
    speed = speeds.get(transportation, 24)
    return max(5, round((distance / speed) * 60 + (8 if transportation == 'public' else 3)))


@dataclass(frozen=True)
class RankedDestination:
    destination: object
    score: float
    content_score: float
    collaborative_score: float
    context_score: float
    reasons: tuple

    def payload(self):
        return {
            'match_percent': round(self.score * 100),
            'reasons': list(self.reasons),
            'signals': {
                'content': round(self.content_score * 100),
                'collaborative': round(self.collaborative_score * 100),
                'context': round(self.context_score * 100),
            },
        }


class HybridRecommendationEngine:
    """Blend content, collaborative, and trip-context signals for destinations."""

    def __init__(self, preferences, user=None):
        self.preferences = preferences
        self.user = user if getattr(user, 'is_authenticated', False) else None
        self.interests = normalized_values(preferences.get('interests', []))
        self.categories = normalized_values(preferences.get('preferred_categories', []))
        self.selected_order = list(preferences.get('preferred_destinations', []))
        self.selected_ids = set(self.selected_order)
        self.companion = str(preferences.get('companion', '')).strip().lower()
        self.transport = str(preferences.get('transportation', '')).strip().lower()
        self.pace = str(preferences.get('pace', 'balanced')).strip().lower()
        self.accessibility = str(preferences.get('accessibility', '')).strip().lower()
        self.accessibility_tokens = text_tokens(self.accessibility)
        self.travelers = max(1, int(preferences.get('travelers') or 1))
        self.budget = Decimal(str(preferences.get('budget_max') or preferences.get('budget') or 0))
        self.budget_min = Decimal(str(preferences.get('budget_min') or 0))
        self.available_minutes = minutes_between(preferences.get('available_start_time'), preferences.get('available_end_time'))
        self.available_start_time = preferences.get('available_start_time')
        self.available_end_time = preferences.get('available_end_time')
        self.latitude = preferences.get('latitude')
        self.longitude = preferences.get('longitude')
        self.collaborative_scores, self.history_samples = self._collaborative_scores()
        self.collaborative_enabled = False

    def _history_similarity(self, saved):
        preferences = saved.preferences if isinstance(saved.preferences, dict) else {}
        similarity = jaccard_similarity(self.interests, normalized_values(preferences.get('interests', []))) * 0.65
        similarity += 0.15 if self.companion and str(preferences.get('companion', '')).lower() == self.companion else 0
        similarity += 0.10 if self.transport and str(preferences.get('transportation', '')).lower() == self.transport else 0
        similarity += 0.10 if self.pace and str(preferences.get('pace', '')).lower() == self.pace else 0
        if self.user and saved.owner_id == self.user.pk:
            similarity += 0.15
        return min(similarity, 1)

    def _collaborative_scores(self):
        affinity = defaultdict(float)
        evidence_samples = 0
        history = SavedItinerary.objects.only('preferences', 'itinerary', 'owner_id')[:MAX_HISTORY_SAMPLES]
        for saved in history:
            destination_ids = itinerary_destination_ids(saved.itinerary)
            similarity = self._history_similarity(saved)
            if not destination_ids or similarity <= 0:
                continue
            evidence_samples += 1
            for destination_id in destination_ids:
                affinity[destination_id] += similarity
        maximum = max(affinity.values(), default=0)
        if maximum:
            affinity = {destination_id: value / maximum for destination_id, value in affinity.items()}
        return affinity, evidence_samples

    def _content_score(self, destination):
        destination_interests = normalized_values(destination.interests)
        overlap = self.interests & destination_interests
        score = (len(overlap) / len(self.interests)) * 0.62 if self.interests else 0
        normalized_category = destination.category.strip().lower()
        category_match = normalized_category in self.categories or normalized_category in self.interests
        if self.categories and normalized_category in self.categories:
            score += 0.28
        elif category_match:
            score += 0.18
        activities = destination.activities if isinstance(destination.activities, list) else []
        searchable_text = ' '.join([destination.category, destination.description, *map(str, activities)])
        activity_match = bool(self.interests & text_tokens(searchable_text))
        if activity_match:
            score += 0.10
        return min(score, 1), overlap

    def _context_score(self, destination):
        points = 0.0
        possible = 0.0
        reasons = []

        possible += 0.25
        companions = ' '.join(normalized_values(destination.recommended_companions))
        companion_aliases = {
            'solo': ('solo',), 'couple': ('couple',), 'family': ('family', 'families'),
            'friends': ('friend', 'group'), 'senior': ('senior',),
        }
        if self.companion and any(alias in companions for alias in companion_aliases.get(self.companion, (self.companion,))):
            points += 0.25
            reasons.append(f'Suits {self.companion} trips')

        if self.budget:
            possible += 0.25
            max_stops = {'relaxed': 2, 'balanced': 3, 'fast': 4}.get(self.pace, 3)
            per_stop_budget = self.budget / max_stops
            group_fee = destination.entrance_fee * self.travelers
            if group_fee <= per_stop_budget:
                points += 0.25
                reasons.append('Fits your group budget')
            elif group_fee <= per_stop_budget * Decimal('1.35'):
                points += 0.10

        if self.accessibility:
            possible += 0.25
            accessibility_text = destination.accessibility.lower()
            token_match = bool(self.accessibility_tokens & text_tokens(accessibility_text))
            if token_match:
                points += 0.25
                reasons.append('Matches accessibility needs')
            elif accessibility_text:
                points += 0.10

        transport_options = ' '.join(normalized_values(destination.transportation_options))
        if transport_options:
            possible += 0.15
            if self.transport in transport_options:
                points += 0.15
                reasons.append(f'Supports {self.transport} transport')

        possible += 0.10
        if not destination.advisory:
            points += 0.10

        possible += 0.15
        ideal_minutes = {'relaxed': 90, 'balanced': 120, 'fast': 150}.get(self.pace, 120)
        difference = abs(destination.visit_minutes - ideal_minutes)
        points += 0.15 * max(0, 1 - (difference / max(ideal_minutes, 1)))

        if self.available_minutes:
            possible += 0.20
            if destination.visit_minutes <= self.available_minutes:
                points += 0.20
                reasons.append('Fits your available travel time')

            available_start = clock_minutes(self.available_start_time)
            available_end = clock_minutes(self.available_end_time)
            destination_start = clock_minutes(destination.opening_time)
            destination_end = clock_minutes(destination.closing_time)
            if None not in (available_start, available_end, destination_start, destination_end):
                possible += 0.15
                overlapping_minutes = min(available_end, destination_end) - max(available_start, destination_start)
                if overlapping_minutes >= destination.visit_minutes:
                    points += 0.15
                    reasons.append('Open during your available hours')

        distance = distance_kilometers(self.latitude, self.longitude, destination)
        travel_minutes = estimated_travel_minutes(distance, self.transport)
        if travel_minutes is not None:
            possible += 0.20
            time_window = self.available_minutes or 480
            if travel_minutes <= max(30, time_window * 0.25):
                points += 0.20
                reasons.append('Close to your starting point')
            elif travel_minutes <= max(60, time_window * 0.45):
                points += 0.10

        possible += 0.10
        average_rating = getattr(destination, 'average_rating', None)
        review_count = getattr(destination, 'review_count', 0) or 0
        if average_rating is not None:
            points += 0.07 * min(float(average_rating) / 5, 1)
        if review_count:
            points += 0.03 * min(review_count / 10, 1)

        possible += 0.05
        if destination.is_verified:
            points += 0.05
            reasons.append('Verified by the tourism office')

        return (points / possible if possible else 0.5), reasons

    def rank(self, destinations):
        use_collaborative = bool(
            self.history_samples
            and any(self.collaborative_scores.get(destination.id, 0) > 0 for destination in destinations)
        )
        self.collaborative_enabled = use_collaborative
        ranked = []
        for destination in destinations:
            content_score, overlap = self._content_score(destination)
            context_score, context_reasons = self._context_score(destination)
            collaborative_score = self.collaborative_scores.get(destination.id, 0)
            if use_collaborative:
                score = content_score * 0.52 + collaborative_score * 0.23 + context_score * 0.25
            else:
                score = content_score * 0.65 + context_score * 0.35
            reasons = []
            if destination.id in self.selected_ids:
                score += 0.30
                reasons.append('One of your selected places')
            if overlap:
                reasons.append(f"Matches {', '.join(sorted(overlap)[:2])}")
            if collaborative_score >= 0.15:
                reasons.append('Popular in similar saved trips')
            reasons.extend(context_reasons)
            if not reasons:
                reasons.append('Balanced fit for your trip settings')
            ranked.append(RankedDestination(
                destination=destination,
                score=min(score, 1),
                content_score=content_score,
                collaborative_score=collaborative_score,
                context_score=context_score,
                reasons=tuple(dict.fromkeys(reasons))[:MAX_REASON_COUNT],
            ))
        selected_position = {destination_id: index for index, destination_id in enumerate(self.selected_order)}
        ranked.sort(key=lambda item: (
            -item.score,
            selected_position.get(item.destination.id, 999),
            item.destination.name.casefold(),
        ))
        return ranked

    def metadata(self):
        return {
            'name': 'hybrid',
            'strategy': 'content + collaborative + contextual' if self.collaborative_enabled else 'content + contextual cold start',
            'history_samples': self.history_samples,
            'collaborative_enabled': self.collaborative_enabled,
        }


def tourist_preference_input(profile):
    return {
        'interests': profile.interests,
        'preferred_categories': profile.preferred_categories,
        'budget_min': profile.budget_min,
        'budget_max': profile.budget_max,
        'available_start_time': profile.available_start_time,
        'available_end_time': profile.available_end_time,
        'pace': profile.preferred_pace,
        'transportation': profile.preferred_transportation,
        'companion': profile.traveler_type,
        'accessibility': profile.accessibility_needs,
        'latitude': profile.latitude,
        'longitude': profile.longitude,
        'travelers': 1,
    }


def build_preference_recommendations(profile, destinations, user=None):
    """Return database-backed recommendation references for later ID validation."""
    preferences = tourist_preference_input(profile)
    engine = HybridRecommendationEngine(preferences, user=user)
    ranked = engine.rank(list(destinations))
    recommendations = []
    for item in ranked:
        distance = distance_kilometers(profile.latitude, profile.longitude, item.destination)
        travel_minutes = estimated_travel_minutes(distance, profile.preferred_transportation)
        reason = '. '.join(item.reasons).rstrip('.') + '.'
        recommendations.append({
            'destination_id': item.destination.id,
            'match_score': min(100, max(0, round(item.score * 100))),
            'recommendation_reason': f'Recommended because {reason[0].lower()}{reason[1:]}',
            'estimated_travel_minutes': travel_minutes,
            'estimated_travel_time': f'About {travel_minutes} minutes' if travel_minutes is not None else 'Estimate unavailable',
            'distance_km': round(distance, 1) if distance is not None else None,
            'signals': item.payload()['signals'],
        })
    return recommendations, engine.metadata()

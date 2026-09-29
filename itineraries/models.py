from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from datetime import time
import re


class Destination(models.Model):
    """Tourism-office verified information used by the itinerary engine."""

    name = models.CharField(max_length=180)
    description = models.TextField()
    category = models.CharField(max_length=80)
    interests = models.JSONField(default=list)
    address = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    opening_time = models.TimeField()
    closing_time = models.TimeField()
    operating_days = models.JSONField(default=list)
    availability_start = models.DateField(null=True, blank=True)
    availability_end = models.DateField(null=True, blank=True)
    visit_minutes = models.PositiveIntegerField()
    entrance_fee = models.DecimalField(max_digits=10, decimal_places=2)
    activities = models.JSONField(default=list, blank=True)
    accessibility = models.CharField(max_length=255, blank=True)
    contact_information = models.CharField(max_length=255, blank=True)
    image_url = models.URLField(blank=True)
    image = models.FileField(
        upload_to='destinations/%Y/%m/', blank=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp'])],
    )
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    transportation_options = models.JSONField(default=list, blank=True)
    safety_reminders = models.JSONField(default=list, blank=True)
    recommended_companions = models.JSONField(default=list, blank=True)
    advisory = models.CharField(max_length=255, blank=True)
    area = models.CharField(max_length=100)
    province_code = models.CharField(max_length=10, blank=True, db_index=True)
    municipality_code = models.CharField(max_length=10, blank=True, db_index=True)
    barangay_code = models.CharField(max_length=10, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        for field in ('name', 'address', 'area'):
            value = getattr(self, field)
            if isinstance(value, str):
                setattr(self, field, value.strip())
        for field in ('interests', 'operating_days', 'activities', 'transportation_options', 'safety_reminders', 'recommended_companions'):
            values = getattr(self, field)
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                errors[field] = 'Provide a list of text values.'
                continue
            normalized = []
            seen = set()
            for value in values:
                cleaned = value.strip()
                if cleaned and cleaned.casefold() not in seen:
                    normalized.append(cleaned)
                    seen.add(cleaned.casefold())
            setattr(self, field, normalized)
        for field in ('province_code', 'municipality_code', 'barangay_code'):
            code = getattr(self, field)
            if code and (not isinstance(code, str) or not re.fullmatch(r'[0-9]{10}', code)):
                errors[field] = 'Choose a valid 10-digit PSGC code.'
        if self.barangay_code and not self.municipality_code:
            errors['barangay_code'] = 'Choose a city or municipality first.'
        if isinstance(self.name, str) and isinstance(self.address, str) and self.name and self.address:
            original = Destination.objects.filter(pk=self.pk).values('name', 'address').first() if self.pk else None
            identity_changed = not original or (
                original['name'].strip().casefold(), original['address'].strip().casefold()
            ) != (self.name.casefold(), self.address.casefold())
            if identity_changed and Destination.objects.filter(
                name__iexact=self.name, address__iexact=self.address,
            ).exclude(pk=self.pk).exists():
                errors['name'] = 'A destination with this name and address already exists.'
        try:
            latitude = Decimal(self.latitude)
            longitude = Decimal(self.longitude)
            if not -90 <= latitude <= 90:
                errors['latitude'] = 'Latitude must be between -90 and 90.'
            if not -180 <= longitude <= 180:
                errors['longitude'] = 'Longitude must be between -180 and 180.'
        except (InvalidOperation, TypeError, ValueError):
            errors['coordinates'] = 'Latitude and longitude must be valid numbers.'
        if self.opening_time and self.closing_time and self.opening_time >= self.closing_time:
            errors['closing_time'] = 'Closing time must be later than opening time.'
        if self.availability_start and self.availability_end and self.availability_start > self.availability_end:
            errors['availability_end'] = 'The availability end date must be on or after the start date.'
        if not self.visit_minutes or self.visit_minutes <= 0:
            errors['visit_minutes'] = 'Visiting duration must be greater than zero.'
        if self.entrance_fee is None or self.entrance_fee < 0:
            errors['entrance_fee'] = 'Entrance fee cannot be negative.'
        if not isinstance(self.interests, list) or not self.interests:
            errors['interests'] = 'At least one destination interest is required.'
        if not isinstance(self.operating_days, list) or not self.operating_days:
            errors['operating_days'] = 'At least one operating day is required.'
        if errors:
            raise ValidationError(errors)


class SiteSettings(models.Model):
    """The single, staff-managed identity used across public and admin pages."""

    site_name = models.CharField(max_length=80, default='Travel Osmena')
    tagline = models.CharField(max_length=180, default='Your local escape, thoughtfully planned.')
    organization_name = models.CharField(max_length=180, default='Sergio Osmeña Sr. Tourism Office')
    municipality_name = models.CharField(max_length=180, default='Sergio Osmeña Sr., Zamboanga del Norte')
    support_email = models.EmailField(blank=True)
    support_phone = models.CharField(max_length=40, blank=True)
    logo = models.FileField(
        upload_to='branding/', blank=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp'])],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Site settings'

    def __str__(self):
        return self.site_name

    @classmethod
    def load(cls):
        settings_record, _ = cls.objects.get_or_create(pk=1)
        return settings_record

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)


class SavedItinerary(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='saved_itineraries')
    name = models.CharField(max_length=150)
    travel_date = models.DateField()
    preferences = models.JSONField(default=dict)
    itinerary = models.JSONField(default=dict)
    signature = models.CharField(max_length=64, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [models.UniqueConstraint(fields=['owner', 'signature'], name='unique_owner_itinerary_signature')]

    def __str__(self):
        return self.name


class TouristProfile(models.Model):
    """Traveler-owned profile details and reusable itinerary preferences."""

    PACE_CHOICES = [('relaxed', 'Relaxed'), ('balanced', 'Balanced'), ('fast', 'Fast-paced')]
    TRANSPORT_CHOICES = [
        ('public', 'Public transit'), ('motorcycle', 'Motorcycle taxi'),
        ('private', 'Private vehicle'), ('walking', 'Walking'),
    ]
    LANGUAGE_CHOICES = [('English', 'English'), ('Filipino', 'Filipino'), ('Cebuano', 'Cebuano')]
    TRAVELER_CHOICES = [
        ('solo', 'Solo traveler'), ('couple', 'Couple'), ('family', 'Family'),
        ('friends', 'Friend group'), ('senior', 'Senior traveler'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tourist_profile')
    display_name = models.CharField(max_length=120, blank=True)
    home_location = models.CharField(max_length=180, blank=True)
    bio = models.CharField(max_length=500, blank=True)
    interests = models.JSONField(default=list, blank=True)
    preferred_categories = models.JSONField(default=list, blank=True)
    budget_min = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    budget_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    available_start_time = models.TimeField(default=time(8, 0))
    available_end_time = models.TimeField(default=time(17, 0))
    preferred_pace = models.CharField(max_length=20, choices=PACE_CHOICES, default='balanced')
    preferred_transportation = models.CharField(max_length=20, choices=TRANSPORT_CHOICES, default='public')
    traveler_type = models.CharField(max_length=20, choices=TRAVELER_CHOICES, default='solo')
    preferred_language = models.CharField(max_length=20, choices=LANGUAGE_CHOICES, default='English')
    accessibility_needs = models.CharField(max_length=255, blank=True)
    starting_location = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    onboarding_completed = models.BooleanField(default=False)
    typical_budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.get_username()} travel profile'

    def clean(self):
        errors = {}
        if self.budget_min is not None and self.budget_min < 0:
            errors['budget_min'] = 'Minimum budget cannot be negative.'
        if self.budget_max is not None and self.budget_max < 0:
            errors['budget_max'] = 'Maximum budget cannot be negative.'
        if self.budget_min is not None and self.budget_max is not None and self.budget_min > self.budget_max:
            errors['budget_max'] = 'Maximum budget must be greater than or equal to minimum budget.'
        if self.available_start_time and self.available_end_time and self.available_start_time >= self.available_end_time:
            errors['available_end_time'] = 'Available end time must be later than the start time.'
        if (self.latitude is None) != (self.longitude is None):
            errors['coordinates'] = 'Latitude and longitude must be provided together.'
        if self.latitude is not None and not Decimal('-90') <= self.latitude <= Decimal('90'):
            errors['latitude'] = 'Latitude must be between -90 and 90.'
        if self.longitude is not None and not Decimal('-180') <= self.longitude <= Decimal('180'):
            errors['longitude'] = 'Longitude must be between -180 and 180.'
        if errors:
            raise ValidationError(errors)


class DestinationReview(models.Model):
    """A tourist's destination rating, public comment, and private improvement suggestion."""

    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='reviews')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='destination_reviews')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(max_length=1200, blank=True)
    suggestion = models.TextField(max_length=1200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['destination', 'author'], name='unique_tourist_destination_review'),
        ]

    def __str__(self):
        return f'{self.destination} - {self.rating}/5 by {self.author}'

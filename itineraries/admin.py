from django.contrib import admin

from .models import Destination, DestinationReview, SavedItinerary, TouristProfile


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'area', 'is_verified', 'is_active', 'entrance_fee')
    list_filter = ('category', 'area', 'is_verified', 'is_active')
    search_fields = ('name', 'address', 'description')


@admin.register(SavedItinerary)
class SavedItineraryAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'travel_date', 'created_at', 'updated_at')
    list_filter = ('travel_date',)
    search_fields = ('name', 'owner__username')


@admin.register(TouristProfile)
class TouristProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'display_name', 'home_location', 'preferred_pace', 'preferred_transportation', 'updated_at')
    list_filter = ('preferred_pace', 'preferred_transportation', 'preferred_language')
    search_fields = ('user__username', 'user__email', 'display_name', 'home_location')


@admin.register(DestinationReview)
class DestinationReviewAdmin(admin.ModelAdmin):
    list_display = ('destination', 'author', 'rating', 'updated_at')
    list_filter = ('rating', 'destination')
    search_fields = ('destination__name', 'author__username', 'comment', 'suggestion')
    readonly_fields = ('created_at', 'updated_at')

from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.db import DatabaseError
from django.utils.deconstruct import deconstructible

from .models import StoredMedia


@deconstructible
class DatabaseMediaStorage(Storage):
    """Store bounded photo uploads in MySQL when the app has no persistent disk."""

    def _open(self, name, mode='rb'):
        if mode != 'rb':
            raise ValueError('Stored media can only be opened for reading.')
        try:
            record = StoredMedia.objects.only('content').get(name=name)
        except StoredMedia.DoesNotExist as error:
            raise FileNotFoundError(name) from error
        return ContentFile(bytes(record.content), name=name)

    def get_available_name(self, name, max_length=None):
        # Independent uploads never overwrite each other, including concurrent
        # requests using the same original filename.
        path = PurePosixPath(str(name).replace('\\', '/'))
        candidate = str(path.parent / f'{uuid4().hex}{path.suffix.lower()}')
        return super().get_available_name(candidate, max_length=max_length).replace('\\', '/')

    def _save(self, name, content):
        data = b''.join(content.chunks())
        if len(data) > 5 * 1024 * 1024:
            raise OSError('Stored images must be 5 MB or smaller.')
        try:
            StoredMedia.objects.create(name=name, content=data, size=len(data))
        except DatabaseError as error:
            raise OSError('The database could not store the uploaded image.') from error
        return name

    def exists(self, name):
        return StoredMedia.objects.filter(name=name).exists()

    def delete(self, name):
        StoredMedia.objects.filter(name=name).delete()

    def size(self, name):
        try:
            return StoredMedia.objects.values_list('size', flat=True).get(name=name)
        except StoredMedia.DoesNotExist as error:
            raise FileNotFoundError(name) from error

    def get_modified_time(self, name):
        try:
            return StoredMedia.objects.values_list('updated_at', flat=True).get(name=name)
        except StoredMedia.DoesNotExist as error:
            raise FileNotFoundError(name) from error

    def url(self, name):
        return settings.MEDIA_URL.rstrip('/') + '/' + quote(name)

import base64
import hashlib
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage, StorageHandler, default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import DatabaseError
from django.test import TestCase, override_settings

from .models import Destination, SiteSettings, StoredMedia


DATABASE_STORAGES = {
    'default': {'BACKEND': 'itineraries.storage.DatabaseMediaStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


@override_settings(STORAGES=DATABASE_STORAGES, SECURE_SSL_REDIRECT=False)
class DatabaseMediaTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.media_root = Path(temporary.name)
        media_settings = override_settings(MEDIA_ROOT=self.media_root)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        self.destination = Destination.objects.create(
            name='Test Falls', description='A verified nature stop.', category='Nature',
            interests=['nature'], address='Test address', latitude=9.7, longitude=123.4,
            opening_time='08:00', closing_time='17:00', operating_days=['Monday'],
            visit_minutes=60, entrance_fee=0, area='Test Area', is_verified=True,
        )
        staff = get_user_model().objects.create_user(username='media-admin', password='secure-pass', is_staff=True)
        self.client.force_login(staff)

    def upload_cover(self):
        response = self.client.post(f'/api/admin/destinations/{self.destination.pk}/image/', {
            'image': SimpleUploadedFile('cover.png', PNG, content_type='image/png'),
        })
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['destination']['image_url']

    def assert_public_image(self, url, content):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, f'Image not served: {url}')
        self.assertTrue(response.headers['Content-Type'].startswith('image/'))
        self.assertEqual(b''.join(response.streaming_content), content)

    @override_settings(DEBUG=False)
    def test_cover_and_logo_survive_replaced_container_filesystem(self):
        cover_url = self.upload_cover()
        response = self.client.post('/api/admin/settings/logo/', {
            'logo': SimpleUploadedFile('logo.png', PNG, content_type='image/png'),
        })
        self.assertEqual(response.status_code, 200, response.content)
        logo_url = response.json()['settings']['logo_url']
        self.assertEqual(StoredMedia.objects.count(), 2)
        self.assertEqual(list(self.media_root.iterdir()), [])
        with tempfile.TemporaryDirectory() as rebuilt_media, self.settings(MEDIA_ROOT=Path(rebuilt_media)):
            restarted_storage = StorageHandler(backends=DATABASE_STORAGES)['default']
            with restarted_storage.open(cover_url.removeprefix('/media/')) as cover:
                self.assertEqual(cover.read(), PNG)
            self.assert_public_image(cover_url, PNG)
            self.assert_public_image(logo_url, PNG)

    def test_replacing_cover_keeps_new_image_and_removes_old_image(self):
        old_url = self.upload_cover()
        new_url = self.upload_cover()
        self.assertNotEqual(old_url, new_url)
        self.assertEqual(StoredMedia.objects.count(), 1)
        self.assertEqual(self.client.get(old_url).status_code, 404)
        self.assert_public_image(new_url, PNG)

    def test_database_write_failure_keeps_previous_cover(self):
        cover_url = self.upload_cover()
        with patch.object(StoredMedia.objects, 'create', side_effect=DatabaseError('storage unavailable')):
            with self.assertLogs('itineraries', level='ERROR'):
                response = self.client.post(f'/api/admin/destinations/{self.destination.pk}/image/', {
                    'image': SimpleUploadedFile('new-cover.png', PNG, content_type='image/png'),
                })
        self.assertEqual(response.status_code, 503)
        self.destination.refresh_from_db()
        self.assertEqual(self.destination.image.url, cover_url)
        self.assert_public_image(cover_url, PNG)

    def test_replacing_logo_returns_the_new_image_url(self):
        urls = []
        for _ in range(2):
            response = self.client.post('/api/admin/settings/logo/', {
                'logo': SimpleUploadedFile('logo.png', PNG, content_type='image/png'),
            })
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()['settings']['has_logo'])
            urls.append(response.json()['settings']['logo_url'])
        self.assertNotEqual(*urls)
        self.assertEqual(self.client.get(urls[0]).status_code, 404)
        self.assert_public_image(urls[1], PNG)

    def test_import_retains_existing_urls_and_never_overwrites_saved_content(self):
        name = 'destinations/2026/09/legacy.png'
        filesystem = FileSystemStorage()
        filesystem.save(name, SimpleUploadedFile('legacy.png', PNG))
        self.destination.image = name
        self.destination.save(update_fields=['image'])
        call_command('import_media', stdout=StringIO())
        self.assert_public_image('/media/' + name, PNG)
        Path(filesystem.path(name)).write_bytes(b'different content')
        call_command('import_media', stdout=StringIO())
        self.assertEqual(StoredMedia.objects.count(), 1)
        self.assert_public_image('/media/' + name, PNG)

    def test_confirmed_backup_restores_missing_cover_and_logo_without_disk_volume(self):
        cover_name = 'destinations/2026/09/Luoip.jpg'
        logo_name = 'branding/Luoip.jpg'
        self.destination.image = cover_name
        self.destination.save(update_fields=['image'])
        SiteSettings.objects.create(logo=logo_name)
        call_command('import_media', stdout=StringIO())
        self.assertEqual(StoredMedia.objects.count(), 2)
        expected = (settings.BASE_DIR / 'media/destinations/2026/08/Luoip.jpg').read_bytes()
        self.assertEqual(hashlib.sha256(expected).hexdigest(), '50743940362cc80d367147065aad155ed751e733c710f37cf347b5c766832d9f')
        self.assert_public_image('/media/' + cover_name, expected)
        self.assert_public_image('/media/' + logo_name, expected)
        self.assertEqual(list(self.media_root.iterdir()), [])
        call_command('import_media', stdout=StringIO())
        self.assertEqual(StoredMedia.objects.count(), 2)

    def test_import_reports_missing_original_without_creating_fake_image(self):
        self.destination.image = 'destinations/2026/09/missing.png'
        self.destination.save(update_fields=['image'])
        warnings = StringIO()
        call_command('import_media', stdout=StringIO(), stderr=warnings)
        self.assertIn('Missing original', warnings.getvalue())
        self.assertFalse(StoredMedia.objects.exists())

    def test_startup_storage_probe_leaves_no_rows_or_files(self):
        call_command('check_media_storage', stdout=StringIO())
        self.assertEqual(StoredMedia.objects.count(), 0)
        self.assertEqual(list(self.media_root.iterdir()), [])

    def test_private_paths_are_not_public_and_missing_photos_return_404(self):
        StoredMedia.objects.create(name='private.txt', content=b'private', size=7)
        self.assertEqual(self.client.get('/media/private.txt').status_code, 404)
        self.assertEqual(self.client.get('/media/destinations/2026/09/missing.png').status_code, 404)

    def test_storage_metadata_and_delete(self):
        url = self.upload_cover()
        name = url.removeprefix('/media/')
        self.assertEqual(default_storage.size(name), len(PNG))
        self.assertIsNotNone(default_storage.get_modified_time(name))
        response = self.client.delete(f'/api/admin/destinations/{self.destination.pk}/image/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(default_storage.exists(name))
        self.assertEqual(self.client.get(url).status_code, 404)

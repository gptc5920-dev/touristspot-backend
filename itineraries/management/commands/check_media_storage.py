import os
import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from itineraries.models import Destination, SiteSettings


class Command(BaseCommand):
    help = 'Check media directory access and optionally find missing destination photos and logos.'

    def add_arguments(self, parser):
        parser.add_argument('--check-files', action='store_true', help='Check database references against stored files.')

    def handle(self, *args, **options):
        root = settings.MEDIA_ROOT
        try:
            os.makedirs(root, exist_ok=True)
            with tempfile.TemporaryFile(dir=root) as probe:
                probe.write(b'media-storage-check')
                probe.flush()
                probe.seek(0)
                if probe.read() != b'media-storage-check':
                    raise OSError('Media storage failed the read/write check.')
        except OSError as error:
            raise CommandError(f'MEDIA_ROOT is not readable and writable: {root}. {error}') from error

        self.stdout.write(self.style.SUCCESS(f'Media directory is readable and writable: {root}'))
        if not settings.DEBUG and not os.environ.get('MEDIA_ROOT'):
            self.stderr.write(self.style.WARNING(
                'MEDIA_ROOT is not configured. Mount persistent storage and set MEDIA_ROOT to its path; '
                'files in the application directory may be lost during redeployment.'
            ))

        if options['check_files']:
            missing = []
            for model, field in ((Destination, 'image'), (SiteSettings, 'logo')):
                for record in model.objects.exclude(**{field: ''}).only('pk', field).iterator():
                    upload = getattr(record, field)
                    if not upload.storage.exists(upload.name):
                        missing.append(f'{model.__name__} {record.pk}: {upload.name}')
            if missing:
                raise CommandError('Missing uploaded files:\n' + '\n'.join(missing))
            self.stdout.write(self.style.SUCCESS('All referenced photos and logos exist.'))

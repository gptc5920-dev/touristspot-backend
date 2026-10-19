import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage, FileSystemStorage
from django.core.management.base import BaseCommand

from itineraries.models import Destination, SiteSettings, StoredMedia
from itineraries.storage import DatabaseMediaStorage


class Command(BaseCommand):
    help = 'Copy referenced local images into database storage without changing their public URLs.'

    def add_arguments(self, parser):
        parser.add_argument('--recovery-manifest', default=str(settings.BASE_DIR / 'deploy' / 'media-recovery.json'))

    def handle(self, *args, **options):
        if not isinstance(default_storage, DatabaseMediaStorage):
            return
        filesystem = FileSystemStorage()
        manifest_path = Path(options['recovery_manifest'])
        recovery = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
        names = set(Destination.objects.exclude(image='').values_list('image', flat=True))
        names.update(SiteSettings.objects.exclude(logo='').values_list('logo', flat=True))
        for name in sorted(names):
            if default_storage.exists(name):
                continue
            data = None
            if filesystem.exists(name):
                with filesystem.open(name, 'rb') as source:
                    data = source.read(5 * 1024 * 1024 + 1)
            elif name in recovery:
                backup = recovery[name]
                source_path = (settings.BASE_DIR / backup['source']).resolve()
                if source_path.is_relative_to(settings.BASE_DIR.resolve()) and source_path.is_file():
                    with source_path.open('rb') as source:
                        candidate = source.read(5 * 1024 * 1024 + 1)
                    if hashlib.sha256(candidate).hexdigest() == backup['sha256']:
                        data = candidate
            if data is None:
                self.stderr.write(self.style.WARNING(f'Missing original; restore or re-upload: {name}'))
                continue
            if len(data) > 5 * 1024 * 1024:
                self.stderr.write(self.style.WARNING(f'Skipping image larger than 5 MB: {name}'))
                continue
            _, created = StoredMedia.objects.get_or_create(name=name, defaults={'content': data, 'size': len(data)})
            if created:
                self.stdout.write(self.style.SUCCESS(f'Imported {name}'))

from django.db import migrations


DEMO_DESTINATION_NAMES = (
    'Dalaguete Beach Park',
    'Liloan Peak Viewpoint',
    'Mantalongon Public Market',
    'Obong Spring',
    'Osmena Peak',
    'San Guillermo de Aquitania Parish',
)


def remove_demo_destinations(apps, schema_editor):
    Destination = apps.get_model('itineraries', 'Destination')
    Destination.objects.filter(name__in=DEMO_DESTINATION_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [('itineraries', '0003_saveditinerary_owner')]

    operations = [migrations.RunPython(remove_demo_destinations, migrations.RunPython.noop)]

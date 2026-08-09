import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('itineraries', '0005_alter_destination_area_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='destination',
            name='activities',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='destination',
            name='availability_end',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='destination',
            name='availability_start',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='destination',
            name='image',
            field=models.FileField(
                blank=True,
                upload_to='destinations/%Y/%m/',
                validators=[django.core.validators.FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp'])],
            ),
        ),
        migrations.AlterField(
            model_name='destination',
            name='recommended_companions',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name='destination',
            name='safety_reminders',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name='destination',
            name='transportation_options',
            field=models.JSONField(blank=True, default=list),
        ),
    ]

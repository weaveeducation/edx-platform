# Generated by Django 2.2.13 on 2020-11-16 11:30

import common.djangoapps.credo_modules.models
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
import opaque_keys.edx.django.models


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0056_rutgers_campus_mapping'),
    ]

    operations = [
        migrations.CreateModel(
            name='CopyBlockTask',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('task_id', models.CharField(max_length=255, unique=True)),
                ('block_ids', models.TextField()),
                ('dst_location', models.CharField(db_index=True, max_length=255)),
                ('status', models.CharField(choices=[('not_started', 'Not Started'), ('started', 'Started'), ('finished', 'Finished'), ('error', 'Error')], default='not_started', max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.DeleteModel(
            name='CopySectionTask',
        ),
    ]

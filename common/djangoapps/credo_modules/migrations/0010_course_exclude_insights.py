# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from opaque_keys.edx.django.models import CourseKeyField


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0009_organization_default_frame_domain'),
    ]

    operations = [
        migrations.CreateModel(
            name='CourseExcludeInsights',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('course_id', CourseKeyField(db_index=True, max_length=255, null=True, blank=True)),
            ],
            options={
                'db_table': 'credo_course_exclude_insights',
                'verbose_name': 'course',
                'verbose_name_plural': 'exclude insights',
            },
        ),
    ]

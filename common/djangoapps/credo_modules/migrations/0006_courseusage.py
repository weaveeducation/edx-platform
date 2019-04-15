# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.conf import settings
from opaque_keys.edx.django.models import CourseKeyField


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('credo_modules', '0005_termperorg'),
    ]

    operations = [
        migrations.CreateModel(
            name='CourseUsage',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('course_id', CourseKeyField(db_index=True, max_length=255, null=True, blank=True)),
                ('usage_count', models.IntegerField(null=True)),
                ('first_usage_time', models.DateTimeField(null=True, verbose_name=b'First Usage Time', blank=True)),
                ('last_usage_time', models.DateTimeField(null=True, verbose_name=b'Last Usage Time', blank=True)),
                ('user', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]

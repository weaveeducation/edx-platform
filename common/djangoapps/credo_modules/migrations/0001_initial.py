# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.conf import settings
from opaque_keys.edx.django.models import CourseKeyField


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CredoModulesUserProfile',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('course_id', CourseKeyField(max_length=255, db_index=True)),
                ('meta', models.TextField(blank=True)),
                ('fields_version', models.CharField(max_length=80)),
                ('user', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('user', 'course_id'),
                'db_table': 'credo_modules_userprofile',
            },
        ),
        migrations.AlterUniqueTogether(
            name='credomodulesuserprofile',
            unique_together=set([('user', 'course_id')]),
        ),
    ]

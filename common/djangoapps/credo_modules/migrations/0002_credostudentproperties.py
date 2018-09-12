# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import openedx.core.djangoapps.xmodule_django.models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('credo_modules', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CredoStudentProperties',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('course_id', openedx.core.djangoapps.xmodule_django.models.CourseKeyField(db_index=True, max_length=255, null=True, blank=True)),
                ('name', models.CharField(max_length=255, db_index=True)),
                ('value', models.CharField(max_length=255)),
                ('user', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('user', 'course_id', 'name'),
                'db_table': 'credo_student_properties',
            },
        ),
    ]

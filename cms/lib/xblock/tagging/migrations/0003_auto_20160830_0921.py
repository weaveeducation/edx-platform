# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import xmodule_django.models


class Migration(migrations.Migration):

    dependencies = [
        ('tagging', '0002_data__add_tags'),
    ]

    operations = [
        migrations.AddField(
            model_name='tagavailablevalues',
            name='course_id',
            field=xmodule_django.models.CourseKeyField(db_index=True, max_length=255, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='tagcategories',
            name='editable_in_studio',
            field=models.BooleanField(default=False, verbose_name='Editable in studio'),
        ),
        migrations.AddField(
            model_name='tagcategories',
            name='scoped_by_course',
            field=models.BooleanField(default=False, verbose_name='Scoped by course'),
        ),
    ]

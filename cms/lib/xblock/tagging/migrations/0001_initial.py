# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import xmodule_django.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='AvailableTags',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('course_id', xmodule_django.models.CourseKeyField(max_length=255, db_index=True)),
                ('category', models.CharField(db_index=True, max_length=32, choices=[(b'difficulty_tag', b'difficulty_tag'), (b'learning_outcome_tag', b'learning_outcome_tag')])),
                ('tag', models.CharField(max_length=255)),
            ],
            options={
                'ordering': ('id',),
            },
        ),
        migrations.AlterUniqueTogether(
            name='availabletags',
            unique_together=set([('course_id', 'category', 'tag')]),
        ),
    ]

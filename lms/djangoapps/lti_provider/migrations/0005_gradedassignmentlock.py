# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lti_provider', '0004_auto_20170831_0729'),
    ]

    operations = [
        migrations.CreateModel(
            name='GradedAssignmentLock',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('graded_assignment_id', models.IntegerField(unique=True)),
                ('created', models.DateTimeField()),
            ],
        ),
    ]

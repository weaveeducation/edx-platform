# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0006_courseusage'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='courseusage',
            unique_together=set([('user', 'course_id')]),
        ),
    ]

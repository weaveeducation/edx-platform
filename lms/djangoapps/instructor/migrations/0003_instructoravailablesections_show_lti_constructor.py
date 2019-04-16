# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('instructor', '0002_instructoravailablesections_show_open_responses'),
    ]

    operations = [
        migrations.AddField(
            model_name='instructoravailablesections',
            name='show_lti_constructor',
            field=models.BooleanField(default=True, verbose_name=b'Show "Link Constructor" section'),
        ),
    ]

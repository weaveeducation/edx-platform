# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('instructor', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='instructoravailablesections',
            name='show_certificates',
            field=models.BooleanField(default=True, verbose_name=b'Show "Certificates" section'),
        ),
    ]

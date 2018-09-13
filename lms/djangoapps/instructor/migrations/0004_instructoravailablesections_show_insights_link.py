# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('instructor', '0003_instructoravailablesections_show_lti_constructor'),
    ]

    operations = [
        migrations.AddField(
            model_name='instructoravailablesections',
            name='show_insights_link',
            field=models.BooleanField(default=True, verbose_name=b'Show "Credo Insights" section'),
        ),
    ]

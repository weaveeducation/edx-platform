# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0008_organization'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='default_frame_domain',
            field=models.CharField(help_text=b'Default value is https://frame.credocourseware.com in case of empty field', max_length=255, null=True, verbose_name=b'Domain for LTI/Iframe/etc', blank=True),
        ),
    ]

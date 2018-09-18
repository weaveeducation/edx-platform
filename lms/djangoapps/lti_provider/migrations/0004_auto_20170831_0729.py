# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lti_provider', '0003_auto_20161118_1040'),
    ]

    operations = [
        migrations.AddField(
            model_name='lticonsumer',
            name='allow_to_add_instructors_via_lti',
            field=models.NullBooleanField(
            help_text=b"Automatically adds instructor role to the user who came through the LTI if some of these parameters: 'Administrator', 'Instructor', 'Staff' was passed. Choose 'Yes' to enable this feature. "),
        ),
        migrations.AddField(
            model_name='lticonsumer',
            name='lti_strict_mode',
            field=models.NullBooleanField(
            help_text=b"More strict validation rules for requests from the consumer LMS (according to the LTI standard) .Choose 'Yes' to enable strict mode."),
        ),
    ]


# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0007_auto_20171212_0535'),
    ]

    operations = [
        migrations.CreateModel(
            name='Organization',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('org', models.CharField(unique=True, max_length=255, verbose_name=b'Org')),
                ('is_courseware_customer', models.BooleanField(default=False, verbose_name=b'Courseware customer')),
                ('is_skill_customer', models.BooleanField(default=False, verbose_name=b'SKILL customer')),
                ('is_modules_customer', models.BooleanField(default=False, verbose_name=b'Modules customer')),
            ],
        ),
    ]

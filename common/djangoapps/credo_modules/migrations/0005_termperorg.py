# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0004_auto_20170615_0525'),
    ]

    operations = [
        migrations.CreateModel(
            name='TermPerOrg',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('org', models.CharField(max_length=255, verbose_name=b'Org', db_index=True)),
                ('term', models.CharField(max_length=255, verbose_name=b'Term')),
                ('start_date', models.DateField(verbose_name=b'Start Date')),
                ('end_date', models.DateField(verbose_name=b'End Date')),
            ],
        ),
    ]


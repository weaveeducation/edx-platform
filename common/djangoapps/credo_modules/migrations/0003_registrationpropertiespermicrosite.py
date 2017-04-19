# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0002_credostudentproperties'),
    ]

    operations = [
        migrations.CreateModel(
            name='RegistrationPropertiesPerMicrosite',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('org', models.CharField(unique=True, max_length=255, verbose_name=b'Org')),
                ('domain', models.CharField(unique=True, max_length=255, verbose_name=b'Microsite Domain Name')),
                ('data', models.TextField(help_text=b'Config in JSON format', verbose_name=b'Registration Properties')),
            ],
            options={
                'db_table': 'credo_registration_properties',
                'verbose_name': 'registration properties item',
                'verbose_name_plural': 'registration properties per microsite',
            },
        ),
    ]

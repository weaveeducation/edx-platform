# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('third_party_auth', '0002_schema__provider_icon_image'),
    ]

    operations = [
        migrations.CreateModel(
            name='SAMLConfigurationPerMicrosite',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('domain', models.CharField(unique=True, max_length=255, verbose_name=b'Microsite Domain Name')),
                ('entity_id', models.CharField(default=b'http://saml.example.com', max_length=255, verbose_name=b'Entity ID')),
                ('org_info_str', models.TextField(default=b'{"en-US": {"url": "http://www.example.com", "displayname": "Example Inc.", "name": "example"}}', help_text=b"JSON dictionary of 'url', 'displayname', and 'name' for each language", verbose_name=b'Organization Info')),
                ('other_config_str', models.TextField(default=b'{\n"SECURITY_CONFIG": {"metadataCacheDuration": 604800, "signMetadata": false}\n}', help_text=b'JSON object defining advanced settings that are passed on to python-saml. Valid keys that can be set here include: SECURITY_CONFIG and SP_EXTRA')),
            ],
            options={
                'verbose_name': 'SAML Configuration per Microsite',
                'verbose_name_plural': 'SAML Configuration per Microsite',
            },
        ),
        migrations.AddField(
            model_name='samlconfiguration',
            name='separate_settings_per_microsite',
            field=models.BooleanField(default=False, verbose_name=b'Separate Settings per Microsite'),
        ),
    ]

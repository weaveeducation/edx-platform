# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tagging', '0003_auto_20160830_0921'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='tagavailablevalues',
            options={'ordering': ('id',), 'verbose_name': 'tag available value'},
        ),
        migrations.AlterModelOptions(
            name='tagcategories',
            options={'ordering': ('title',), 'verbose_name': 'tag category'},
        ),
        migrations.AddField(
            model_name='tagcategories',
            name='role',
            field=models.CharField(max_length=64, null=True, verbose_name='Access role', blank=True),
        ),
    ]

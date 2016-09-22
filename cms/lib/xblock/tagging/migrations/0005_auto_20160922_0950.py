# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tagging', '0004_auto_20160919_1046'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='tagcategories',
            options={'ordering': ('title',), 'verbose_name': 'tag category', 'verbose_name_plural': 'tag categories'},
        ),
        migrations.RemoveField(
            model_name='tagcategories',
            name='scoped_by_course',
        ),
        migrations.AddField(
            model_name='tagavailablevalues',
            name='org',
            field=models.CharField(db_index=True, max_length=255, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='tagcategories',
            name='scoped_by',
            field=models.CharField(max_length=64, null=True, verbose_name='Scoped by', blank=True),
        ),
    ]

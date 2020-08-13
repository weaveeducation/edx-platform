# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from opaque_keys.edx.django.models import CourseKeyField


class Migration(migrations.Migration):

    dependencies = [
        ('tagging', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='tagavailablevalues',
            options={'ordering': ('id',), 'verbose_name': 'available tag value'},
        ),
        migrations.AlterModelOptions(
            name='tagcategories',
            options={'ordering': ('title',), 'verbose_name': 'tag category', 'verbose_name_plural': 'tag categories'},
        ),
        migrations.AddField(
            model_name='tagavailablevalues',
            name='course_id',
            field=CourseKeyField(db_index=True, max_length=255, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='tagavailablevalues',
            name='org',
            field=models.CharField(db_index=True, max_length=255, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='tagcategories',
            name='editable_in_studio',
            field=models.BooleanField(default=False, verbose_name='Editable in studio'),
        ),
        migrations.AddField(
            model_name='tagcategories',
            name='role',
            field=models.CharField(max_length=64, null=True, verbose_name='Access role', blank=True),
        ),
        migrations.AddField(
            model_name='tagcategories',
            name='scoped_by',
            field=models.CharField(max_length=255, null=True, verbose_name='Scoped by', blank=True),
        ),
        migrations.AlterField(
            model_name='tagcategories',
            name='name',
            field=models.CharField(max_length=255),
        ),
    ]

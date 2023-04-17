# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0050_usagelog_update'),
    ]

    operations = [
        migrations.CreateModel(
            name='EnrollmentLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('course_id', models.CharField(max_length=255)),
                ('org_id', models.CharField(max_length=80)),
                ('course', models.CharField(max_length=255)),
                ('run', models.CharField(max_length=80)),
                ('term', models.CharField(blank=True, max_length=20, null=True)),
                ('user_id', models.IntegerField(db_index=True)),
                ('ts', models.IntegerField()),
                ('is_staff', models.SmallIntegerField(default=0)),
                ('course_user_id', models.CharField(max_length=255, null=True)),
                ('update_ts', models.IntegerField()),
                ('update_process_num', models.IntegerField(db_index=True, null=True)),
            ],
        ),
        migrations.AlterIndexTogether(
            name='enrollmentlog',
            index_together=set([('org_id', 'ts')]),
        ),
    ]

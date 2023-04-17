# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0010_course_exclude_insights'),
    ]

    operations = [
        migrations.AddField(
            model_name='courseusage',
            name='block_id',
            field=models.CharField(max_length=255, null=True, db_index=True),
        ),
        migrations.AddField(
            model_name='courseusage',
            name='block_type',
            field=models.CharField(max_length=32, null=True,
                                   choices=[('problem', 'problem'), ('video', 'video'),
                                            ('html', 'html'), ('course', 'course'), ('chapter', 'Section'),
                                            ('sequential', 'Subsection'), ('vertical', 'Vertical'),
                                            ('library_content', 'Library Content')]),
        ),
        migrations.AddField(
            model_name='courseusage',
            name='session_ids',
            field=models.TextField(null=True, blank=True),
        ),
        migrations.RunSQL("UPDATE credo_modules_courseusage SET block_type='course', block_id='course';"),
        migrations.AlterUniqueTogether(
            name='courseusage',
            unique_together=set([('user', 'course_id', 'block_id')]),
        ),
    ]

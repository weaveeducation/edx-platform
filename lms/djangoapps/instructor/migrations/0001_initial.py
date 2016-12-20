# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InstructorAvailableSections',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('show_course_info', models.BooleanField(default=True, verbose_name=b'Show "Course Info" section')),
                ('show_membership', models.BooleanField(default=True, verbose_name=b'Show "Membership" section')),
                ('show_cohort', models.BooleanField(default=True, verbose_name=b'Show "Cohorts" section')),
                ('show_student_admin', models.BooleanField(default=True, verbose_name=b'Show "Student Admin" section')),
                ('show_data_download', models.BooleanField(default=True, verbose_name=b'Show "Data Download" section')),
                ('show_email', models.BooleanField(default=True, verbose_name=b'Show "Email" section')),
                ('show_analytics', models.BooleanField(default=True, verbose_name=b'Show "Analytics" section')),
                ('show_certificates', models.BooleanField(default=True, verbose_name=b'Show "Certificates" section')),
                ('show_studio_link', models.BooleanField(default=True, verbose_name=b'Show "View In Studio" link')),
                ('user', models.OneToOneField(related_name='instructor_dashboard_tabs', null=True, on_delete=django.db.models.deletion.SET_NULL, blank=True, to=settings.AUTH_USER_MODEL, verbose_name=b'Instructor')),
            ],
            options={
                'verbose_name': 'Instructor dashboard available sections',
                'verbose_name_plural': 'Instructor dashboard available sections',
            },
        ),
    ]

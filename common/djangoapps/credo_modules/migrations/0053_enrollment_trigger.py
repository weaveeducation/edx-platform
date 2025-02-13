# Generated by Django 2.2.13 on 2020-09-22 10:07

import common.djangoapps.credo_modules.models
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0052_auto_20200918_2229'),
    ]

    operations = [
        migrations.CreateModel(
            name='EnrollmentTrigger',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(max_length=255)),
                ('course_id', models.CharField(max_length=255)),
                ('user_id', models.IntegerField(db_index=True)),
                ('time', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
        ),
    ]

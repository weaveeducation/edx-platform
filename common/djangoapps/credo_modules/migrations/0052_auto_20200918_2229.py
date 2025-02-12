# Generated by Django 2.2.13 on 2020-09-18 22:29

import common.djangoapps.credo_modules.models
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0051_enrollmentlog'),
    ]

    operations = [
        migrations.AlterField(
            model_name='enrollmentlog',
            name='update_ts',
            field=models.IntegerField(db_index=True),
        ),
        migrations.AlterUniqueTogether(
            name='enrollmentlog',
            unique_together={('course_id', 'user_id')},
        ),
    ]

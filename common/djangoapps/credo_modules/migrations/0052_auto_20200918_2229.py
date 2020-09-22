from django.db import migrations, models


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

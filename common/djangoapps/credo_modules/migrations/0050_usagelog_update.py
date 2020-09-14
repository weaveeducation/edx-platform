from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0049_usagelog'),
    ]

    operations = [
        migrations.RenameField(
            model_name='usagelog',
            old_name='parent_path',
            new_name='section_path',
        ),
    ]

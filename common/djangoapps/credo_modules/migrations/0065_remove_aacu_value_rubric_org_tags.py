from django.db import migrations, models


def remove_aacu_value_rubric_org_tags(apps, schema_editor):
    OrganizationTag = apps.get_model('credo_modules', 'OrganizationTag')
    OrganizationTag.objects.filter(tag_name='AAC&U VALUE Rubric').delete()

class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0064_siblingblocknotupdated_siblingblockupdatetask'),
    ]

    operations = [
        migrations.RunPython(remove_aacu_value_rubric_org_tags),
    ]

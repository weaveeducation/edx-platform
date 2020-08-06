# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


def add_types(apps, schema_editor):
    OrganizationType = apps.get_model("credo_modules", "OrganizationType")
    OrganizationType.objects.create(
        title="Modules - video only",
        constructor_lti_link=False,
        constructor_embed_code=True,
        constructor_direct_link=True,
        insights_learning_outcomes=False,
        insights_assessments=False,
        insights_enrollment=False,
        insights_engagement=True,
        instructor_dashboard_credo_insights=True
    )
    OrganizationType.objects.create(
        title="K12 without assessment",
        constructor_lti_link=False,
        constructor_embed_code=True,
        constructor_direct_link=True,
        insights_learning_outcomes=False,
        insights_assessments=False,
        insights_enrollment=False,
        insights_engagement=True,
        instructor_dashboard_credo_insights=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0012_organization_types'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='organization',
            name='is_courseware_customer',
        ),
        migrations.RemoveField(
            model_name='organization',
            name='is_modules_customer',
        ),
        migrations.RemoveField(
            model_name='organization',
            name='is_skill_customer',
        ),
        migrations.RunPython(
            add_types,
        ),
    ]

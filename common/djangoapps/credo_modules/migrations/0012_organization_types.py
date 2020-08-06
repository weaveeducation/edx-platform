# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


def update_types(apps, schema_editor):
    Organization = apps.get_model("credo_modules", "Organization")
    OrganizationType = apps.get_model("credo_modules", "OrganizationType")
    courseware_type = OrganizationType.objects.create(
        title="Courseware",
        constructor_lti_link=True,
        constructor_embed_code=False,
        constructor_direct_link=False,
        insights_learning_outcomes=True,
        insights_assessments=True,
        insights_enrollment=True,
        insights_engagement=True,
        instructor_dashboard_credo_insights=True
    )
    k12_type = OrganizationType.objects.create(
        title="K12 with assessment",
        constructor_lti_link=False,
        constructor_embed_code=True,
        constructor_direct_link=True,
        insights_learning_outcomes=True,
        insights_assessments=True,
        insights_enrollment=True,
        insights_engagement=True,
        instructor_dashboard_credo_insights=False
    )
    modules_type = OrganizationType.objects.create(
        title="Modules",
        constructor_lti_link=True,
        constructor_embed_code=True,
        constructor_direct_link=True,
        insights_learning_outcomes=False,
        insights_assessments=True,
        insights_enrollment=True,
        insights_engagement=True,
        instructor_dashboard_credo_insights=True
    )
    for org in Organization.objects.all():
        if org.is_courseware_customer:
            org.org_type = courseware_type
        elif org.is_skill_customer:
            org.org_type = k12_type
        elif org.is_modules_customer:
            org.org_type = modules_type
        org.save()


class Migration(migrations.Migration):

    dependencies = [
        ('credo_modules', '0011_courseusage_add_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrganizationType',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('title', models.CharField(unique=True, max_length=255, verbose_name=b'Title')),
                ('constructor_lti_link', models.BooleanField(default=True, verbose_name=b'Display LTI link in Constructor')),
                ('constructor_embed_code', models.BooleanField(default=True, verbose_name=b'Display embed code field in Constructor')),
                ('constructor_direct_link', models.BooleanField(default=True, verbose_name=b'Display direct link in Constructor')),
                ('insights_learning_outcomes', models.BooleanField(default=True, verbose_name=b'Display LO report in Credo Insights')),
                ('insights_assessments', models.BooleanField(default=True, verbose_name=b'Display Assessment report in Credo Insights')),
                ('insights_enrollment', models.BooleanField(default=True, verbose_name=b'Display Enrollment report in Credo Insights')),
                ('insights_engagement', models.BooleanField(default=True, verbose_name=b'Display Engagement report in Credo Insights')),
                ('instructor_dashboard_credo_insights', models.BooleanField(default=True, verbose_name=b'Show Credo Insights link in the Instructor Dashboard')),
            ],
        ),
        migrations.AlterField(
            model_name='organization',
            name='default_frame_domain',
            field=models.CharField(validators=[django.core.validators.URLValidator()], max_length=255, blank=True, help_text=b'Default value is https://frame.credocourseware.com in case of empty field', null=True, verbose_name=b'Domain for LTI/Iframe/etc'),
        ),
        migrations.AlterField(
            model_name='organization',
            name='is_skill_customer',
            field=models.BooleanField(default=False, verbose_name=b'K12 with assessment'),
        ),
        migrations.AddField(
            model_name='organization',
            name='org_type',
            field=models.ForeignKey(related_name='org_type', null=True, on_delete=django.db.models.deletion.SET_NULL, blank=True, to='credo_modules.OrganizationType', verbose_name=b'Org Type'),
        ),
        migrations.RunPython(
            update_types,
        ),
    ]

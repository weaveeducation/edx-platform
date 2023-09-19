import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q

from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from common.djangoapps.credo_modules.models import OrganizationType, Organization, CourseToRemove, OrgToRemove
from common.djangoapps.credo_modules.services.global_data_remover import GlobalDataRemover
from common.djangoapps.badgr_integration.models import Configuration as BadgrConfiguration
from openedx.core.djangoapps.site_configuration.models import SiteConfiguration
from openedx.core.djangoapps.theming.models import SiteTheme

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    """
    /sbin/setuser app /venv/bin/python /home/app/edxapp/edx-platform/manage.py lms remove_weave_data --mongo --settings=production
    /sbin/setuser app /venv/bin/python /home/app/edxapp/edx-platform/manage.py lms remove_weave_data --mysql --settings=production
    /sbin/setuser app /venv/bin/python /home/app/edxapp/edx-platform/manage.py lms remove_weave_data --vertica --settings=production
    /sbin/setuser app /venv/bin/python /home/app/edxapp/edx-platform/manage.py lms remove_weave_data --full --mysql --settings=production
    """

    help = "Remove Weave Data"
    credo_org_types = [
        "K12 with assessment",
        "Modules",
        "Modules - video only",
        "K12 without assessment"
    ]

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", default=False)
        parser.add_argument("--mongo", action="store_true", default=False)
        parser.add_argument("--mysql", action="store_true", default=False)
        parser.add_argument("--vertica", action="store_true", default=False)

    def handle(self, full, mongo, mysql, vertica, *args, **options):
        site_name_remove = "weave"
        org_types = [org_type.id for org_type in OrganizationType.objects.exclude(title__in=self.credo_org_types)]
        orgs_to_remove_cnt = OrgToRemove.objects.filter(site_name=site_name_remove).count()

        if not orgs_to_remove_cnt:
            orgs = [o.org for o in Organization.objects.filter(org_type_id__in=org_types)]
            course_ids = [str(co.id) for co in CourseOverview.objects.filter(org__in=orgs)]

            insert_orgs_data = []
            insert_courses_data = []
            for org in orgs:
                insert_orgs_data.append(OrgToRemove(
                    site_name=site_name_remove,
                    org_id=org
                ))
            for course_id in course_ids:
                insert_courses_data.append(CourseToRemove(
                    site_name=site_name_remove,
                    course_id=course_id
                ))

            # create cache
            OrgToRemove.objects.bulk_create(insert_orgs_data)
            CourseToRemove.objects.bulk_create(insert_courses_data)
        else:
            orgs = [o.org_id for o in OrgToRemove.objects.filter(site_name=site_name_remove)]
            course_ids = [c.course_id for c in CourseToRemove.objects.filter(site_name=site_name_remove)]

        BadgrConfiguration.objects.all().delete()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM turnitin_submission WHERE 1=1")
            cursor.execute("DELETE FROM turnitin_user WHERE 1=1")
            cursor.execute("DELETE FROM turnitin_api_key WHERE 1=1")

        gdr = GlobalDataRemover(orgs, course_ids, full, mongo, mysql, vertica)
        gdr.remove_all_data()

        SiteConfiguration.objects.filter(
            Q(site__domain__icontains='weaveeducation') | Q(site__domain__icontains='nimblywise')).delete()
        SiteTheme.objects.filter(
            Q(site__domain__icontains='weaveeducation') | Q(site__domain__icontains='nimblywise')).delete()

import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from common.djangoapps.credo_modules.models import OrganizationType, Organization, CourseToRemove, OrgToRemove
from common.djangoapps.credo_modules.services.global_data_remover import GlobalDataRemover
from openedx.core.djangoapps.site_configuration.models import SiteConfiguration
from openedx.core.djangoapps.theming.models import SiteTheme

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):

    help = "Remove Credo Data"
    credo_org_types = [
        "K12 with assessment",
        "Modules",
        "Modules - video only",
        "K12 without assessment"
    ]

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", default=False)

    def handle(self, full, *args, **options):
        site_name_remove = "credo"
        org_types = [org_type.id for org_type in OrganizationType.objects.filter(title__in=self.credo_org_types)]
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

        gdr = GlobalDataRemover(orgs, course_ids, full)
        gdr.remove_all_data()

        SiteConfiguration.objects.filter(site__domain__icontains='credocourseware').delete()
        SiteTheme.objects.filter(site__domain__icontains='credocourseware').delete()

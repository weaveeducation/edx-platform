import logging
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from common.djangoapps.credo_modules.models import OrganizationType, Organization

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):

    help = "Get Weave Courses and Orgs"
    credo_org_types = [
        "K12 with assessment",
        "Modules",
        "Modules - video only",
        "K12 without assessment"
    ]

    def handle(self, *args, **options):
        org_types = [org_type.id for org_type in OrganizationType.objects.exclude(title__in=self.credo_org_types)]
        orgs = [o.org for o in Organization.objects.filter(org_type_id__in=org_types)]
        course_ids = [str(co.id) for co in CourseOverview.objects.filter(org__in=orgs)]
        print('Weave ORGS:', json.dumps(orgs))
        print('Weave COURSES:', json.dumps(course_ids))

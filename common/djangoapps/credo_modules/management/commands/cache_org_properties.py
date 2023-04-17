from django.core.management import BaseCommand
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from common.djangoapps.credo_modules.properties_updater import PropertiesUpdater


class Command(BaseCommand):

    def handle(self, *args, **options):
        props_updater = PropertiesUpdater()

        course_overviews = CourseOverview.objects.all().order_by('id')
        for course_overview in course_overviews:
            org = course_overview.org
            course_id = str(course_overview.id)
            props_updater.update_props_for_course(org, course_id)

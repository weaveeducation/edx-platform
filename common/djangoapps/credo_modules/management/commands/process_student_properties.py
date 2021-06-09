import json

from django.core.management import BaseCommand
from opaque_keys.edx.keys import CourseKey
from common.djangoapps.credo_modules.models import PropertiesInfo, TrackingLogProp
from openedx.core.djangoapps.enrollments.data import get_user_enrollments
from common.djangoapps.credo_modules.properties_updater import PropertiesUpdater


class Command(BaseCommand):
    _props_updater = None

    def process_course(self, course_id, org_props, course_props):
        course_key = CourseKey.from_string(course_id)
        enrollments = get_user_enrollments(course_key)
        data_to_insert = []

        for enrollment in enrollments:
            log_prop = self._props_updater.update_props_for_course_and_user(course_id, enrollment.user.id, org_props)
            if log_prop:
                data_to_insert.append(log_prop)

        if data_to_insert:
            TrackingLogProp.objects.bulk_create(data_to_insert, 2000)
        print('------------------ Values inserted: ', len(data_to_insert))

    def handle(self, *args, **options):
        prop_org_info_lst = PropertiesInfo.objects.filter(course_id__isnull=True)
        self._props_updater = PropertiesUpdater()

        for prop_org_info in prop_org_info_lst:
            print('--- Start process org: ', prop_org_info.org)

            try:
                prop_org_info_data = json.loads(prop_org_info.data)
            except ValueError:
                prop_org_info_data = []

            if prop_org_info_data:
                prop_course_info_lst = PropertiesInfo.objects.filter(org=prop_org_info.org)\
                    .exclude(course_id__isnull=True)

                for prop_course_info in prop_course_info_lst:
                    print('--------- Start process course: ', prop_course_info.course_id)
                    try:
                        prop_course_info_data = json.loads(prop_course_info.data)
                    except ValueError:
                        prop_course_info_data = []
                    self.process_course(prop_course_info.course_id, prop_org_info_data, prop_course_info_data)

import json
import time

from django.core.management import BaseCommand
from opaque_keys.edx.keys import CourseKey
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from credo_modules.event_parser import EXCLUDE_PROPERTIES, COURSE_PROPERTIES
from credo_modules.models import RegistrationPropertiesPerMicrosite, RegistrationPropertiesPerOrg,\
    EnrollmentPropertiesPerCourse, PropertiesInfo
from credo_modules.mongo import get_course_structure
from openedx.core.djangoapps.content.block_structure.models import CourseAuthProfileFieldsCache


class Command(BaseCommand):

    def update_prop_info(self, org, course_id, props_lst):
        prop_obj_data = []
        try:
            prop_obj = PropertiesInfo.objects.get(org=org, course_id=course_id)
            prop_obj_data = json.loads(prop_obj.data)
        except PropertiesInfo.DoesNotExist:
            prop_obj = PropertiesInfo(
                org=org,
                course_id=course_id
            )

        for prop in props_lst:
            if prop not in prop_obj_data:
                prop_obj_data.append(prop)

        prop_json = json.dumps(prop_obj_data)
        if prop_json != prop_obj.data:
            prop_obj.data = prop_json
            prop_obj.update_ts = int(time.time())
            prop_obj.save()

    def handle(self, *args, **options):
        exclude_properties = EXCLUDE_PROPERTIES + COURSE_PROPERTIES

        org_courses = {}
        org_props = {}
        course_props = {}

        course_overviews = CourseOverview.objects.all().order_by('id')
        for course_overview in course_overviews:
            course_id = str(course_overview.id)
            if course_overview.org not in org_courses:
                org_courses[course_overview.org] = []
            org_courses[course_overview.org].append(course_id)

        reg_props_models = [RegistrationPropertiesPerMicrosite, RegistrationPropertiesPerOrg]

        for org, course_ids in org_courses.items():
            print 'Prepare properties for org: ', org

            org_common_props = []
            if org not in org_props:
                org_props[org] = []

            for klass in reg_props_models:
                try:
                    reg_props = klass.objects.get(org=org)
                    if reg_props.data:
                        reg_props_data = json.loads(reg_props.data)
                        for k, v in reg_props_data.items():
                            prop_key = k.strip().lower()
                            if prop_key not in org_props[org] and prop_key not in exclude_properties:
                                org_props[org].append(prop_key)
                            if prop_key not in org_common_props and prop_key not in exclude_properties:
                                org_common_props.append(prop_key)
                except klass.DoesNotExist:
                    pass

            for course_id in course_ids:
                course_key = CourseKey.from_string(course_id)
                course_props[course_id] = org_common_props[:]
                properties = EnrollmentPropertiesPerCourse.objects.filter(course_id=course_key).first()
                if properties and properties.data:
                    try:
                        enrollment_properties = json.loads(properties.data)
                    except ValueError:
                        return
                    if enrollment_properties:
                        for k, v in enrollment_properties.items():
                            prop_key = k.strip().lower()
                            if prop_key not in org_props[org] and prop_key not in exclude_properties:
                                org_props[org].append(prop_key)
                            if prop_key not in course_props[course_id] and prop_key not in exclude_properties:
                                course_props[course_id].append(prop_key)

                credo_additional_profile_fields = None

                try:
                    profile_fields_cache = CourseAuthProfileFieldsCache.objects.get(course_id=course_id)
                    credo_additional_profile_fields = profile_fields_cache.get_fields()
                except CourseAuthProfileFieldsCache.DoesNotExist:
                    course_structure = get_course_structure(course_key)
                    if course_structure:
                        for st in course_structure['blocks']:
                            if st['block_type'] == 'course':
                                credo_additional_profile_fields = st.get('fields', {}) \
                                    .get('credo_additional_profile_fields', None)
                                break
                    if credo_additional_profile_fields:
                        profile_fields_cache = CourseAuthProfileFieldsCache(
                            course_id=course_id,
                            data=json.dumps(credo_additional_profile_fields)
                        )
                        profile_fields_cache.save()

                if credo_additional_profile_fields:
                    for k, v in credo_additional_profile_fields.items():
                        prop_key = k.strip().lower()
                        if prop_key not in org_props[org] and prop_key not in exclude_properties:
                            org_props[org].append(prop_key)
                        if prop_key not in course_props[course_id] and prop_key not in exclude_properties:
                            course_props[course_id].append(prop_key)

                self.update_prop_info(org, course_id, course_props[course_id])

            print 'Update properties for org: ', org

            self.update_prop_info(org, None, org_props[org])

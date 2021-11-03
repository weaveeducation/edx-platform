import json
import hashlib
import time

from django.contrib.auth import get_user_model
from opaque_keys.edx.keys import CourseKey
from common.djangoapps.credo_modules.events_processor.utils import EXCLUDE_PROPERTIES, COURSE_PROPERTIES,\
    update_user_info, get_prop_user_info, combine_student_properties
from common.djangoapps.credo_modules.models import RegistrationPropertiesPerMicrosite, RegistrationPropertiesPerOrg,\
    EnrollmentPropertiesPerCourse, PropertiesInfo, TrackingLogProp, get_student_properties_event_data
from openedx.core.djangoapps.content.block_structure.models import CourseFieldsCache


User = get_user_model()


class PropertiesUpdater:
    _org_common_props = None
    _org_props = None
    _course_updated = None
    _users_updated = None
    _show_logs = None
    _users_processed_cache = None

    def __init__(self, show_logs=True):
        self._org_common_props = {}
        self._org_props = {}
        self._course_updated = []
        self._users_updated = []
        self._show_logs = show_logs
        self._users_processed_cache = {}

    def _log(self, msg):
        if self._show_logs:
            print(msg)

    def get_exclude_properties(self):
        return EXCLUDE_PROPERTIES + COURSE_PROPERTIES

    def _get_org_prop_obj(self, org):
        """
        Return org properties using case-sensitive search by org
        """
        prop_obj_data = PropertiesInfo.objects.filter(org=org, course_id=None)
        for prop_obj in prop_obj_data:
            if prop_obj.org == org:
                return prop_obj
        return None

    def _init_org_properties(self, org):
        reg_props_models = [RegistrationPropertiesPerMicrosite, RegistrationPropertiesPerOrg]
        exclude_properties = self.get_exclude_properties()

        if org not in self._org_props:
            self._log('Prepare properties for org: ' + org)

            self._org_props[org] = []
            prop_obj = self._get_org_prop_obj(org)
            if prop_obj:
                self._org_props[org] = json.loads(prop_obj.data)

        if org not in self._org_common_props:
            self._org_common_props[org] = []
            for klass in reg_props_models:
                try:
                    reg_props = klass.objects.get(org=org)
                    if reg_props.data:
                        reg_props_data = json.loads(reg_props.data)
                        for k, v in reg_props_data.items():
                            prop_key = k.strip().lower()
                            if prop_key not in self._org_props[org] and prop_key not in exclude_properties:
                                self._org_props[org].append(prop_key)
                            if prop_key not in self._org_common_props[org] and prop_key not in exclude_properties:
                                self._org_common_props[org].append(prop_key)
                except klass.DoesNotExist:
                    pass

        if org in ['Rutgers', 'Rutgers-University']:
            custom_properties = ['campus', 'school']
            for cust_prop in custom_properties:
                if cust_prop not in self._org_props[org]:
                    self._org_props[org].append(cust_prop)
                if cust_prop not in self._org_common_props[org]:
                    self._org_common_props[org].append(cust_prop)

    def update_prop_info(self, org, course_id, props_lst):
        prop_obj_data = []
        if course_id is None:
            prop_obj = self._get_org_prop_obj(org)
            if not prop_obj:
                prop_obj = PropertiesInfo(
                    org=org,
                    course_id=None
                )
        else:
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

    def update_props_for_course(self, org, course_id):
        if course_id in self._course_updated:
            return

        self._init_org_properties(org)
        self._log('Update properties for course: ' + course_id)

        exclude_properties = self.get_exclude_properties()
        course_key = CourseKey.from_string(course_id)
        course_props = self._org_common_props[org][:]

        properties = EnrollmentPropertiesPerCourse.objects.filter(course_id=course_key).first()
        if properties and properties.data:
            try:
                enrollment_properties = json.loads(properties.data)
            except ValueError:
                return

            if enrollment_properties:
                for k, v in enrollment_properties.items():
                    prop_key = k.strip().lower()
                    if prop_key not in self._org_props[org] and prop_key not in exclude_properties:
                        self._org_props[org].append(prop_key)
                    if prop_key not in course_props and prop_key not in exclude_properties:
                        course_props.append(prop_key)

        course_fields_cache_obj = CourseFieldsCache.get_cache(course_id)
        additional_profile_fields = course_fields_cache_obj.get_additional_profile_fields()
        if additional_profile_fields:
            for k, v in additional_profile_fields.items():
                prop_key = k.strip().lower()
                if prop_key not in self._org_props[org] and prop_key not in exclude_properties:
                    self._org_props[org].append(prop_key)
                if prop_key not in course_props and prop_key not in exclude_properties:
                    course_props.append(prop_key)

        self.update_prop_info(org, course_id, course_props)
        self.update_prop_info(org, None, self._org_props[org])
        self._course_updated.append(course_id)

    def update_props_for_course_and_user(self, course_id, user_id, org_props=None, update_tracking_log_user_info=False,
                                         update_process_num=None):

        key = str(user_id) + '|' + course_id
        if key in self._users_updated:
            return None

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None
        course_key = CourseKey.from_string(course_id)
        org = course_key.org

        course_user_id_source = str(course_id) + '|' + str(user_id)
        course_user_id = hashlib.md5(course_user_id_source.encode('utf-8')).hexdigest()

        if not org_props:
            prop_obj = self._get_org_prop_obj(org)
            if not prop_obj:
                return None
            org_props = json.loads(prop_obj.data)

        props = get_student_properties_event_data(user, course_key, skip_user_profile=True)
        student_properties = props['student_properties']

        kwargs = {
            'course_user_id': course_user_id,
            'org_id': org,
            'course_id': str(course_id),
            'user_id': user_id,
            'update_ts': int(time.time()),
            'update_process_num': update_process_num
        }

        if len(org_props) > TrackingLogProp.MAX_PROPS_COUNT_PER_ORG:
            raise Exception('Count of props exceeds '
                            'permissible max props count: ' + TrackingLogProp.MAX_PROPS_COUNT_PER_ORG)

        if update_tracking_log_user_info:
            tmp_props = combine_student_properties(student_properties)
            prop_user_email, prop_user_name = get_prop_user_info(tmp_props)
            update_user_info(org, user_id, prop_user_email, prop_user_name, self._users_processed_cache)

        for i in range(TrackingLogProp.MAX_PROPS_COUNT_PER_ORG):
            prop_key = 'prop' + str(i)
            kwargs[prop_key] = '(none)'

        for idx, org_prop in enumerate(org_props):
            prop_key = 'prop' + str(idx)
            prop_value = student_properties['enrollment'].get(org_prop, None)
            if not prop_value:
                prop_value = student_properties['registration'].get(org_prop, None)
            if not prop_value:
                prop_value = '(none)'
            if prop_value and len(prop_value) > 255:
                prop_value = prop_value[0:255]
            kwargs[prop_key] = prop_value

        self._users_updated.append(key)

        try:
            log_prop = TrackingLogProp.objects.get(course_user_id=course_user_id)
            need_update = False
            for k, v in kwargs.items():
                if k.startswith('prop'):
                    old_value = getattr(log_prop, k, None)
                    if old_value != v:
                        setattr(log_prop, k, v)
                        need_update = True
                if need_update:
                    log_prop.update_process_num = update_process_num
                    log_prop.update_ts = int(time.time())
                    log_prop.save()
            return None
        except TrackingLogProp.DoesNotExist:
            log_prop = TrackingLogProp(**kwargs)
            return log_prop

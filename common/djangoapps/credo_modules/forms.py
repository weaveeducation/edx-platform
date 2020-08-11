import json
import re

from django.forms import Form, CharField, ChoiceField
from django.conf import settings
from credo_modules.models import StudentAttributesRegistrationModel, RegistrationPropertiesPerOrg
from opaque_keys.edx.keys import CourseKey
from opaque_keys import InvalidKeyError


class StudentAttributesRegistrationForm(Form):
    """
    Extension of basic registration form.
    """
    _org = None
    _passed_post_data = {}
    _registration_attributes = None
    _key_pattern = 'custom_attr_%s'

    def __init__(self, *args, **kwargs):
        request = kwargs.pop('request', None)

        super(StudentAttributesRegistrationForm, self).__init__(*args, **kwargs)

        if 'org' in kwargs:
            self._org = kwargs['org']
        elif request:
            try:
                course_id = request.GET.get('course_id')
                next_url = request.GET.get('next')
                org_id = request.GET.get('org_id')

                if course_id:
                    course_id = course_id.replace(' ', '+')
                    course_key = CourseKey.from_string(course_id)
                    self._org = course_key.org
                elif next_url:
                    course_key = self._parse_course_id_from_string(next_url)
                    if course_key:
                        self._org = course_key.org
                elif org_id:
                    self._org = org_id

            except InvalidKeyError:
                pass

        if 'data' in kwargs:
            self._passed_post_data = kwargs['data']

        try:
            if self._org:
                properties = RegistrationPropertiesPerOrg.objects.get(org=self._org)
            else:
                return
        except RegistrationPropertiesPerOrg.DoesNotExist:
            return

        try:
            self._registration_attributes = json.loads(properties.data)
        except ValueError as e:
            return

        if self._registration_attributes:
            registration_attributes_list = []
            registration_attributes_list_sorted = []

            for k, v in self._registration_attributes.items():
                order = None
                try:
                    order = int(v['order']) if 'order' in v else None
                except ValueError:
                    pass

                required = v['required'] if 'required' in v and v['required'] else False
                title = v['title'] if 'title' in v and v['title'] else k
                default = v['default'] if 'default' in v and v['default'] else None
                options = v['options'] if 'options' in v and v['options'] else None
                required_msq = "%s field is required." % title

                data = {
                    'required': required,
                    'label': title,
                    'initial': default,
                    'error_messages': {
                        "required": required_msq,
                    },
                    'order': order if order else 0,
                    'options': options,
                    'key': self._key_pattern % k
                }

                registration_attributes_list.append(data)

            if registration_attributes_list:
                registration_attributes_list_sorted = sorted(registration_attributes_list, key=lambda k: k.get('order'))

            if registration_attributes_list_sorted:
                for val in registration_attributes_list_sorted:
                    kwargs = val.copy()
                    kwargs.pop('order', None)
                    key = kwargs.pop('key', None)

                    if kwargs['options']:
                        kwargs['choices'] = [(choice, choice) for choice in kwargs['options']]
                        kwargs.pop('options', None)
                        self.fields[key] = ChoiceField(**kwargs)
                    else:
                        kwargs.pop('options', None)
                        self.fields[key] = CharField(**kwargs)

    def _parse_course_id_from_string(self, input_str):
        m_obj = re.match(r'^/courses/{}'.format(settings.COURSE_ID_PATTERN), input_str)
        if m_obj:
            return CourseKey.from_string(m_obj.group('course_id'))
        return None

    def get_org(self):
        return self._org

    def save(self, **kwargs):
        values = []

        if self._registration_attributes:
            for k in self._registration_attributes:
                key = self._key_pattern % k
                if key in self._passed_post_data and self._passed_post_data[key]:
                    values.append({
                        'course_id': None,
                        'name': k,
                        'value': self._passed_post_data[key]
                    })
        return StudentAttributesRegistrationModel(values)

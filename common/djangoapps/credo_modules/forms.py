import json
from django.forms import Form, CharField, ChoiceField
from credo_modules.models import StudentAttributesRegistrationModel, RegistrationPropertiesPerMicrosite
from microsite_configuration import microsite


class StudentAttributesRegistrationForm(Form):
    """
    Extension of basic registration form.
    """
    _org = None
    _passed_post_data = {}
    _registration_attributes = None
    _key_pattern = 'custom_attr_%s'

    def __init__(self, *args, **kwargs):
        super(StudentAttributesRegistrationForm, self).__init__(*args, **kwargs)

        if 'org' in kwargs:
            self._org = kwargs['org']
        if 'data' in kwargs:
            self._passed_post_data = kwargs['data']

        try:
            if self._org:
                properties = RegistrationPropertiesPerMicrosite.objects.get(org=self._org)
            else:
                site_domain = microsite.get_value('site_domain')
                if not site_domain:
                    return
                properties = RegistrationPropertiesPerMicrosite.objects.get(domain=site_domain)
        except RegistrationPropertiesPerMicrosite.DoesNotExist:
            return

        try:
            self._registration_attributes = json.loads(properties.data)
        except ValueError, e:
            return

        if self._registration_attributes:
            registration_attributes_list = []
            registration_attributes_list_sorted = []

            for k, v in self._registration_attributes.iteritems():
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
                    'order': order,
                    'options': options,
                    'key': self._key_pattern % k
                }

                registration_attributes_list.append(data)

            if registration_attributes_list:
                registration_attributes_list_sorted = sorted(registration_attributes_list, key=lambda k: k['order'])

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

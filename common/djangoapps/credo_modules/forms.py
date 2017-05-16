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
            for k, v in self._registration_attributes.iteritems():
                required = v['required'] if 'required' in v and v['required'] else False
                title = v['title'] if 'title' in v and v['title'] else k
                default = v['default'] if 'default' in v and v['default'] else None
                options = v['options'] if 'options' in v and v['options'] else None
                required_msq = "%s field is required." % title
                key = self._key_pattern % k

                kwargs = {
                    'required': required,
                    'label': title,
                    'initial': default,
                    'error_messages': {
                        "required": required_msq,
                    }
                }

                if options:
                    kwargs['choices'] = [(choice, choice) for choice in options]
                    self.fields[key] = ChoiceField(**kwargs)
                else:
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

# -*- coding: utf-8 -*-
"""
XBlockAside to add student properties to the problem_check event
"""

from credo_modules.models import CredoStudentProperties
from django.core.exceptions import ObjectDoesNotExist
from student.models import User, UserProfile
from xblock.core import XBlockAside


class StudentPropertiesAside(XBlockAside):

    def get_event_context(self, event_type, event):  # pylint: disable=unused-argument
        """
        This method return data that should be associated with the "check_problem" event
        """
        if event_type == "problem_check" \
                or event_type.startswith('openassessmentblock.') or event_type.startswith('openassessment.'):
            result = {'registration': {}, 'enrollment': {}}
            user = None

            try:
                user = User.objects.get(pk=self.runtime.user_id)
            except ObjectDoesNotExist:
                pass

            if user:
                profile = UserProfile.objects.get(user=user)
                if profile.gender:
                    result['registration']['gender'] = profile.gender

                #if profile.year_of_birth:
                #    result['registration']['year_of_birth'] = profile.year_of_birth

                properties = CredoStudentProperties.objects.filter(user=user)
                for prop in properties:
                    if not prop.course_id:
                        result['registration'][prop.name] = prop.value
                    elif prop.course_id and str(self.runtime.course_id) == str(prop.course_id):
                        result['enrollment'][prop.name] = prop.value
                return {'student_properties': result}
        return None

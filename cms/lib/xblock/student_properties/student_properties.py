# -*- coding: utf-8 -*-
"""
XBlockAside to add student properties to the problem_check event
"""

from submissions import api as sub_api
from credo_modules.models import get_student_properties_event_data
from django.core.exceptions import ObjectDoesNotExist
from student.models import User, AnonymousUserId
from xblock.core import XBlockAside


class StudentPropertiesAside(XBlockAside):

    def get_event_context(self, event_type, event):  # pylint: disable=unused-argument
        """
        This method return data that should be associated with the "check_problem" event
        """
        event_types_lst = ['openassessmentblock.staff_assess',
                           'openassessmentblock.self_assess',
                           'openassessmentblock.peer_assess']

        user = None
        is_ora = False

        if event_type in event_types_lst and 'submission_uuid' in event:
            is_ora = True
            try:
                submission = sub_api.get_submission_and_student(event['submission_uuid'])
                student_id = submission['student_item']['student_id']
                anonymous_user = AnonymousUserId.objects.get(anonymous_user_id=student_id)
                user = anonymous_user.user
            except ObjectDoesNotExist:
                pass
        elif event_type in ("problem_check", "edx.drag_and_drop_v2.item.dropped") or \
                (event_type == 'openassessmentblock.create_submission' and 'submission_uuid' in event):
            try:
                user = User.objects.get(pk=self.runtime.user_id)
            except ObjectDoesNotExist:
                pass

        if user:
            return get_student_properties_event_data(user, self.runtime.course_id, is_ora)
        return None

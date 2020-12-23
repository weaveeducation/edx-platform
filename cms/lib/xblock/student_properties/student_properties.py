# -*- coding: utf-8 -*-
"""
XBlockAside to add student properties to the problem_check event
"""
import datetime
import pytz

from submissions import api as sub_api
from credo_modules.models import SequentialBlockAnswered, SequentialBlockAttempt, OraBlockScore, OraScoreType,\
    get_student_properties_event_data
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.utils import timezone
from student.models import User, AnonymousUserId
from xblock.core import XBlockAside
from openedx.core.djangoapps.content.block_structure.models import BlockToSequential
from xmodule.modulestore.django import modulestore
from opaque_keys.edx.keys import UsageKey


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
        usage_id = None

        if event_type in event_types_lst and 'submission_uuid' in event:
            course_id = str(self.runtime.course_id)
            org_id = self.runtime.course_id.org
            usage_id = str(self.scope_ids.usage_id.usage_key)
            is_ora = True
            text_response = ''
            submission_answer_parts = event["answer"].get('parts', [])
            text_response_lst = [p['text'] for p in submission_answer_parts if 'text' in p]
            if text_response_lst:
                text_response = "\n".join(text_response_lst).strip()

            try:
                submission = sub_api.get_submission_and_student(event['submission_uuid'])
                student_id = submission['student_item']['student_id']
                anonymous_user = AnonymousUserId.objects.get(anonymous_user_id=student_id)
                user = anonymous_user.user
            except ObjectDoesNotExist:
                pass

            score_type = None
            remove_prev_data = False
            if event['score_type'] == 'PE':
                score_type = OraScoreType.PEER
            elif event['score_type'] == 'ST':
                score_type = OraScoreType.STAFF
                remove_prev_data = True
            elif event['score_type'] == 'SE':
                score_type = OraScoreType.SELF
                remove_prev_data = True

            if remove_prev_data:
                OraBlockScore.objects.filter(
                    course_id=course_id, block_id=usage_id, user=user,
                    score_type=score_type).delete()

            if score_type:
                for crit in event['parts']:
                    ora_score = OraBlockScore(
                        course_id=course_id,
                        org_id=org_id,
                        block_id=usage_id,
                        user=user,
                        answer=text_response,
                        score_type=score_type,
                        criterion=crit.get('criterion').get('name').strip(),
                        option_label=crit.get('option').get('name').strip(),
                        points_possible=crit.get('criterion').get('points_possible'),
                        points_earned=crit.get('option').get('points'),
                        created=timezone.now(),
                        grader_id=self.runtime.user_id
                    )
                    ora_score.save()

        elif event_type in ("problem_check", "edx.drag_and_drop_v2.item.dropped",
                            "xblock.image-explorer.hotspot.opened") or \
                (event_type == 'openassessmentblock.create_submission' and 'submission_uuid' in event):
            usage_id = str(self.scope_ids.usage_id.usage_key)
            try:
                user = User.objects.get(pk=self.runtime.user_id)
            except ObjectDoesNotExist:
                pass

        if user:
            from lms.djangoapps.courseware.tasks import track_sequential_viewed_task
            from lms.djangoapps.courseware.models import StudentModule

            course_id = str(self.runtime.course_id)
            block = BlockToSequential.objects.filter(course_id=course_id, block_id=usage_id).first()
            if block:
                parent_id = block.sequential_id
            else:
                parent_id = self._get_parent_sequential(self.scope_ids.usage_id.usage_key)

            new_attempt = False
            attempt_created = None
            release_date = datetime.datetime(2020, 2, 10, 3, 40, 12, 0, pytz.UTC)

            try:
                SequentialBlockAnswered.objects.get(sequential_id=parent_id, user_id=user.id)
            except SequentialBlockAnswered.DoesNotExist:
                try:
                    st_module = StudentModule.objects.get(
                        course_id=self.runtime.course_id,
                        module_state_key=UsageKey.from_string(parent_id),
                        student=user)
                    if st_module.created > release_date:
                        new_attempt = True
                        attempt_created = st_module.created
                except StudentModule.DoesNotExist:
                    pass

            if new_attempt:
                try:
                    with transaction.atomic():
                        seq_user_block = SequentialBlockAnswered(
                            course_id=course_id,
                            sequential_id=parent_id,
                            first_answered_block_id=usage_id,
                            user_id=user.id
                        )
                        seq_user_block.save()
                        attempt_created = attempt_created - datetime.timedelta(seconds=60)
                        seq_block_attempt = SequentialBlockAttempt(
                            course_id=course_id,
                            sequential_id=parent_id,
                            user_id=user.id,
                            dt=attempt_created
                        )
                        seq_block_attempt.save()

                        StudentModule.log_start_new_attempt(user.id, course_id, parent_id)
                        track_sequential_viewed_task.delay(course_id, parent_id, user.id)
                except IntegrityError:
                    pass

            return get_student_properties_event_data(user, self.runtime.course_id, is_ora, parent_id=parent_id)
        return None

    def _get_parent_sequential(self, usage_id):
        block = modulestore().get_item(usage_id)
        if block.category == 'sequential':
            return str(block.location)
        return self._get_parent_sequential(block.parent) if block.parent else None

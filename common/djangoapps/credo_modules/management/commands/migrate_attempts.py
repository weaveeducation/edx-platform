import datetime
import json

from django.db import transaction
from django.core.management import BaseCommand
from django.utils.timezone import make_aware
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from lms.djangoapps.courseware.models import StudentModule
from lms.djangoapps.lti_provider.models import GradedAssignment
from common.djangoapps.credo_modules.models import AttemptCourseMigration, AttemptUserMigration, DBLogEntry
from openedx.core.djangoapps.content.block_structure.models import BlockToSequential
from edx_proctoring.models import ProctoredExam
from opaque_keys.edx.keys import CourseKey, UsageKey
from eventtracking import tracker


class Command(BaseCommand):

    def handle(self, *args, **options):
        date_from = make_aware(datetime.datetime.strptime('2019-07-02', '%Y-%m-%d'))
        try:
            date_to = StudentModule.objects.get(id=27449224).created
        except StudentModule.DoesNotExist:
            date_to = make_aware(datetime.datetime.now())

        course_overviews = CourseOverview.objects.all().order_by('id')
        for course_overview in course_overviews:
            course_id = str(course_overview.id)
            course_migration = AttemptCourseMigration.objects.filter(course_id=course_id).first()
            if course_migration and course_migration.done:
                print('Skip course: ', course_id)
                continue
            print('Process course: ', course_id)

            exams_list = []
            exams = ProctoredExam.objects.filter(course_id=course_id)
            for exam in exams:
                exams_list.append(str(exam.content_id))

            already_migrated = []
            already_migrated_objs = AttemptUserMigration.objects.filter(course_id=course_id)
            for v in already_migrated_objs:
                already_migrated.append(v.sequential_id + '|' + str(v.user_id))

            graded_assignments = []
            graded_assignments_objs = GradedAssignment.objects.filter(course_key=course_overview.id)
            for gr in graded_assignments_objs:
                graded_assignments.append(str(gr.usage_key) + '|' + str(gr.user_id))

            items = StudentModule.objects.filter(course_id=course_overview.id, module_type='sequential',
                                                 created__gt=date_from, created__lt=date_to)\
                .order_by('module_state_key')
            blocks_dict = {}

            for item in items:
                module_state_key = str(item.module_state_key)
                custom_key = module_state_key + '|' + str(item.student_id)
                if module_state_key in exams_list:
                    print('--> Skip because item is exam', module_state_key, ' -- ', str(item.student_id))
                    continue
                if custom_key in already_migrated:
                    print('--> Skip because item was already migrated', module_state_key, ' -- ', str(item.student_id))
                    continue
#                if module_state_key not in graded_assignments:
#                    print '--> Skip because item is not graded assignment', module_state_key, \
#                        ' -- ', str(item.student_id)
#                    continue

                print('--> Process ', module_state_key, ' -- ', str(item.student_id))
                if module_state_key not in blocks_dict:
                    blocks_dict[module_state_key] = []
                    b2s_data = BlockToSequential.objects.filter(course_id=course_id,
                                                                sequential_id=module_state_key)
                    for b2s in b2s_data:
                        blocks_dict[module_state_key].append(UsageKey.from_string(b2s.block_id))

                student_items_answered_count = StudentModule.objects.filter(
                    course_id=course_overview.id,
                    module_state_key__in=blocks_dict[module_state_key],
                    student_id=item.student_id,
                    grade__isnull=False).count()

                some_ora_answered = False
                ora_answers = StudentModule.objects.filter(
                    course_id=course_overview.id,
                    module_type='openassessment',
                    module_state_key__in=blocks_dict[module_state_key],
                    student_id=item.student_id)
                for ora_answer in ora_answers:
                    try:
                        ora_answer_state = json.loads(ora_answer.state)
                        if 'submission_uuid' in ora_answer_state and ora_answer_state['submission_uuid']:
                            some_ora_answered = True
                            break
                    except ValueError:
                        pass

                some_problem_answered = True if student_items_answered_count > 0 or some_ora_answered else False

                with transaction.atomic():
                    if not some_problem_answered:
                        logs_processed = []
                        log_entries = DBLogEntry.objects.filter(
                            event_name='sequential_block.viewed',
                            user_id=item.student_id,
                            course_id=course_id,
                            block_id__in=blocks_dict[module_state_key]).order_by('-time')
                        for log_entry in log_entries:
                            if log_entry.block_id not in logs_processed:
                                logs_processed.append(log_entry.block_id)
                                log_course_key = CourseKey.from_string(log_entry.course_id)
                                context = {
                                    'user_id': log_entry.user_id,
                                    'org_id': log_course_key.org,
                                    'course_id': str(log_entry.course_id)
                                }
                                log_message_item = json.loads(log_entry.message)

                                with tracker.get_tracker().context('sequential_block.remove_view', context):
                                    tracker.emit('sequential_block.remove_view', log_message_item.get('event', {}))
#                                new_log_entry = DBLogEntry(
#                                    event_name='sequential_block.remove_view',
#                                    user_id=log_entry.user_id,
#                                    course_id=log_entry.course_id,
#                                    block_id=log_entry.block_id,
#                                    message=log_entry.message
#                                )
#                                new_log_entry.save()
                        print('------> Emit events')
                    else:
                        print('------> Some answers exists - Skip')
                    new_attempt_migration = AttemptUserMigration(
                        course_id=course_id,
                        sequential_id=module_state_key,
                        user_id=item.student_id
                    )
                    new_attempt_migration.save()

            with transaction.atomic():
                AttemptCourseMigration(course_id=course_id, done=True).save()

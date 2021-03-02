import datetime
import pytz
import vertica_python

from django.core.management import BaseCommand
from django.db import transaction
from student.models import CourseEnrollment
from lms.djangoapps.courseware.models import StudentModule
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from opaque_keys.edx.keys import CourseKey, UsageKey
from credo_modules.models import AttemptCourseMigration, TrackingLog, DBLogEntry
from credo_modules.mongo import get_course_structure
from credo_modules.vertica import get_vertica_dsn


class Command(BaseCommand):

    def handle(self, *args, **options):
        course_overviews = CourseOverview.objects.all().order_by('id')
        dsn = get_vertica_dsn()
        conn = vertica_python.connect(dsn=dsn)
        cursor = conn.cursor()
        for course_overview in course_overviews:
            course_id = str(course_overview.id)
            course_migration = AttemptCourseMigration.objects.filter(course_id=course_id).first()
            if course_migration and course_migration.done:
                print('Skip course: ', course_id)
                continue
            else:
                self._process_course(course_id, cursor)
                AttemptCourseMigration(course_id=course_id, done=True).save()
                print('Process course: ', course_id)
        print('DONE!')

    def _process_course(self, course_id, cursor=None):
        course_key = CourseKey.from_string(course_id)
        ids_to_remove = []
        db_log_to_remove_lst = []
        org_id = course_key.org
        course = course_key.course
        run = course_key.run
        course_structure = get_course_structure(course_key)
        dt_from = datetime.datetime.strptime('2019-04-01 10:50:22.468797', '%Y-%m-%d %H:%M:%S.%f')\
            .replace(tzinfo=pytz.utc)
        enrollments_fetched = False
        enrolls = []

        if course_structure:
            for block in course_structure['blocks']:
                if block['block_type'] == 'library_content':
                    block_ids = []
                    block_keys = []
                    for c in block['fields']['children']:
                        block_id = 'block-v1:' + org_id + '+' + course + '+' + run + '+type@' + c[0] + '+block@' + c[1]
                        block_ids.append(block_id)
                        block_keys.append(UsageKey.from_string(block_id))
                    if enrollments_fetched is False:
                        enrollments_fetched = True
                        enrolls = CourseEnrollment.objects.filter(
                            created__gt=dt_from,
                            course_id=course_key,
                            is_active=True)
                    if len(enrolls):
                        for enroll in enrolls:
                            user_modules = []
                            student_modules = StudentModule.objects.filter(
                                course_id=course_key,
                                module_state_key__in=block_keys,
                                student_id=enroll.user_id).values('module_state_key')
                            for st_m in student_modules:
                                user_modules.append(str(st_m['module_state_key']))
                            blocks_absent = [block_id for block_id in block_ids if block_id not in user_modules]
                            if blocks_absent:
                                tr_logs = TrackingLog.objects.filter(
                                    org_id=org_id, user_id=enroll.user_id, block_id__in=blocks_absent,
                                    is_view=True, is_last_attempt=1).values('id')
                                if len(tr_logs):
                                    for tr_log in tr_logs:
                                        ids_to_remove.append(tr_log['id'])
                                db_log_entities = DBLogEntry.objects.filter(
                                    event_name='sequential_block.viewed',
                                    user_id=enroll.user_id,
                                    course_id=course_id,
                                    block_id__in=blocks_absent).order_by('-time').values('id', 'block_id')
                                db_log_to_remove_block_ids = []
                                for db_log_entity in db_log_entities:
                                    if db_log_entity['block_id'] not in db_log_to_remove_block_ids:
                                        db_log_to_remove_block_ids.append(db_log_entity['block_id'])
                                        db_log_to_remove_lst.append(db_log_entity['id'])

        if ids_to_remove or db_log_to_remove_lst:
            print('Start remove records')
            with transaction.atomic():
                if ids_to_remove:
                    TrackingLog.objects.filter(
                        org_id=org_id, id__in=ids_to_remove, is_view=True, is_last_attempt=1).delete()
                if db_log_to_remove_lst:
                    DBLogEntry.objects.filter(
                        id__in=db_log_to_remove_lst, event_name='sequential_block.viewed', course_id=course_id).delete()
                if ids_to_remove:
                    ids_to_remove_str = ','.join([str(id2r) for id2r in ids_to_remove])
                    sql = "DELETE FROM credo_modules_trackinglog " \
                          "WHERE org_id='%s' AND id in (%s) AND is_view=1 AND is_last_attempt=1"\
                          % (org_id, ids_to_remove_str)
                    if cursor is not None:
                        cursor.execute(sql)
                        cursor.execute("COMMIT")
            print('Finish remove records')

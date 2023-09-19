import logging
import time
import vertica_python

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Q
from oauth2_provider.models import AccessToken, RefreshToken

from common.djangoapps.student.roles import CourseInstructorRole, CourseStaffRole
from xmodule.contentstore.django import contentstore
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.django import modulestore
from opaque_keys.edx.keys import CourseKey
from completion.models import BlockCompletion
from edx_proctoring.models import ProctoredExam
from lms.djangoapps.courseware.models import StudentModule, StudentModuleHistory
from lms.djangoapps.certificates.models import GeneratedCertificate, CertificateGenerationHistory
from lms.djangoapps.grades.models import PersistentSubsectionGrade, PersistentSubsectionGradeOverride
from lms.djangoapps.lti_provider.models import GradedAssignment
from lms.djangoapps.lti1p3_tool.models import GradedAssignment as GradedAssignmentLti1p3
from lms.djangoapps.instructor_task.models import InstructorTask
from common.djangoapps.badgr_integration.models import Assertion
from common.djangoapps.student.models import CourseEnrollment, CourseEnrollmentAllowed, ManualEnrollmentAudit,\
    UserProfile
from common.djangoapps.credo_modules.vertica import get_vertica_dsn
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructureTags, ApiCourseStructure,\
    ApiCourseStructureUpdateTime, ApiCourseStructureLock, ApiBlockInfo, ApiBlockInfoNotSiblings,\
    ApiBlockInfoVersionsHistory, BlockCache, BlockToSequential, CourseAuthProfileFieldsCache,\
    CourseFieldsCache, OraBlockStructure
from openedx.core.djangoapps.schedules.models import Schedule, ScheduleExperience
from openedx.core.djangoapps.user_api.models import UserPreference
from common.djangoapps.split_modulestore_django.models import SplitModulestoreCourseIndex
from common.djangoapps.student.models import AnonymousUserId, SocialLink, LanguageProficiency
from ..models import SiblingBlockUpdateTask, CredoModulesUserProfile, EnrollmentPropertiesPerCourse,\
    RegistrationPropertiesPerOrg, Organization, OrganizationTag, OrganizationTagOrder,\
    CourseExcludeInsights, SendScores, SiblingBlockNotUpdated, SequentialViewedTask,\
    CourseStaffExtended, SequentialBlockAnswered, SequentialBlockAttempt,\
    AttemptCourseMigration, AttemptUserMigration, PropertiesInfo, OraBlockScore,\
    TrackingLogUserInfo, TrackingLog, EnrollmentLog, EnrollmentTrigger,\
    SupervisorEvaluationInvitation, DelayedTask, DBLogEntry, CourseToRemove


log = logging.getLogger(__name__)
User = get_user_model()


class GlobalDataRemover:

    def __init__(self, orgs, courses_ids, full_remove=False):
        self.orgs = orgs
        self.courses_ids = courses_ids
        self.courses_keys = [CourseKey.from_string(course_id) for course_id in courses_ids]
        self.orgs_num = len(orgs)
        self.courses_num = len(courses_ids)
        self.full_remove = full_remove

    def remove_all_data(self):
        removed_courses_num = self.remove_mongo_courses_data()
        if removed_courses_num > 0:
            self.remove_mongo_library_data()
        self.remove_mysql_courses_data()
        self.remove_vertica_courses_data()

    def _delete_course_from_modulestore(self, course_key, user_id):
        """
        Delete course from MongoDB. Deleting course will fire a signal which will result into
        deletion of the courseware associated with a course_key.
        """
        module_store = modulestore()

        with module_store.bulk_operations(course_key):
            module_store.delete_course(course_key, user_id)

    def _remove_instructors(self, course_key):
        """
        In the django layer, remove all the user/groups permissions associated with this course
        """
        print('removing User permissions from course....')

        try:
            self.remove_all_instructors(course_key)
        except Exception as err:  # lint-amnesty, pylint: disable=broad-except
            log.error(f"Error in deleting course groups for {course_key}: {err}")

    def remove_all_instructors(self,course_key):
        """
        Removes all instructor and staff users from the given course.
        """
        staff_role = CourseStaffRole(course_key)
        staff_role.remove_users(*staff_role.users_with_role())
        instructor_role = CourseInstructorRole(course_key)
        instructor_role.remove_users(*instructor_role.users_with_role())

    def delete_course(self, course_key, user_id, keep_instructors=False):
        """
        Delete course from module store and if specified remove user and
        groups permissions from course.
        """
        self._delete_course_from_modulestore(course_key, user_id)

        if not keep_instructors:
            self._remove_instructors(course_key)

    def delete_orphans(self, course_usage_key, user_id, commit=False):
        """
        Helper function to delete orphans for a given course.
        If `commit` is False, this function does not actually remove
        the orphans.
        """
        store = modulestore()
        blocks = store.get_orphans(course_usage_key)
        branch = course_usage_key.branch
        if commit:
            with store.bulk_operations(course_usage_key):
                for blockloc in blocks:
                    revision = ModuleStoreEnum.RevisionOption.all
                    # specify branches when deleting orphans
                    if branch == ModuleStoreEnum.BranchName.published:
                        revision = ModuleStoreEnum.RevisionOption.published_only
                    store.delete_item(blockloc, user_id, revision=revision)
        return [str(block) for block in blocks]

    def remove_mongo_courses_data(self):
        print("------------- Start MongoDB courses purge -------------")
        removed_courses_num = 0
        for i, course_id in enumerate(self.courses_ids):
            c2r = CourseToRemove.objects.filter(course_id=course_id).first()
            if not c2r:
                raise Exception("CourseToRemove obj not found")
            if c2r.mongo_data_removed:
                print("---- skip ----")
                continue
            print(f"------------- Remove data for course {course_id}, {i+1}/{self.courses_num}")
            course_key = CourseKey.from_string(course_id)
            self.delete_course(course_key, ModuleStoreEnum.UserID.mgmt_command)
            contentstore().delete_all_course_assets(course_key)

            c2r.mongo_data_removed = True
            c2r.save()
            removed_courses_num = removed_courses_num + 1
        return removed_courses_num

    def remove_mongo_library_data(self):
        print("------------- Start MongoDB libraries purge -------------")
        for library_key in modulestore().get_library_keys():
            if library_key.org in self.orgs:
                print(f"------------- Remove data for library {str(library_key)}")
                self.delete_course(library_key, ModuleStoreEnum.UserID.mgmt_command)
                contentstore().delete_all_course_assets(library_key)

    def _remove_from_table(self, cursor, model_obj, field_name, field_value, use_chunks=False):
        table_name = model_obj.objects.model._meta.db_table
        sql = f"DELETE FROM {table_name} WHERE {field_name}"
        if isinstance(field_value, list):
            vals = ','.join([f"'{v}'" for v in field_value])
            sql = sql + f" IN ({vals})"
        else:
            sql = sql + f"='{field_value}'"
        if use_chunks:
            sql = sql + " LIMIT 1000"
            do_delete = True
            while do_delete:
                deleted_rows = cursor.execute(sql)
                if deleted_rows == 0:
                    do_delete = False
        else:
            cursor.execute(sql)

    def remove_mysql_course_data(self, course_id, cursor):
        c2r = CourseToRemove.objects.filter(course_id=course_id).first()
        if not c2r:
            raise Exception("CourseToRemove obj not found")
        if c2r.mysql_data_removed:
            return

        course_key = CourseKey.from_string(course_id)
        t1 = time.time()

        print(f"------------------------------------------ Remove data for {course_id} course --------- start")

        enrolled_course_students = CourseEnrollment.objects.filter(course_id=course_key).exclude(
            Q(user__is_staff=True) | Q(user__is_superuser=True)
        ).values("user_id")
        enrolled_course_users_ids = [s["user_id"] for s in enrolled_course_students]
        user_ids_to_remove = []

        if enrolled_course_users_ids:
            enrolled_other_courses_students = CourseEnrollment.objects.exclude(
                course_id=course_key
            ).filter(
                user_id__in=enrolled_course_users_ids
            ).values("user_id")
            enrolled_other_courses_users_ids = [s["user_id"] for s in enrolled_other_courses_students]

            for s in enrolled_course_students:
                if s["user_id"] not in enrolled_other_courses_users_ids:
                    user_ids_to_remove.append(s["user_id"])

        print(f"------------ Remove {course_id} course structure")
        self._remove_from_table(cursor, ApiCourseStructureTags, 'course_id', course_id)
        self._remove_from_table(cursor, ApiCourseStructureUpdateTime, 'course_id', course_id)
        self._remove_from_table(cursor, ApiCourseStructureLock, 'course_id', course_id)
        self._remove_from_table(cursor, ApiCourseStructure, 'course_id', course_id)
        self._remove_from_table(cursor, ApiBlockInfo, 'course_id', course_id)
        self._remove_from_table(cursor, ApiBlockInfoNotSiblings, 'source_course_id', course_id)
        self._remove_from_table(cursor, ApiBlockInfoNotSiblings, 'dst_course_id', course_id)
        self._remove_from_table(cursor, ApiBlockInfoVersionsHistory, 'course_id', course_id)
        self._remove_from_table(cursor, BlockCache, 'course_id', course_id)
        self._remove_from_table(cursor, BlockToSequential, 'course_id', course_id)
        self._remove_from_table(cursor, CourseAuthProfileFieldsCache, 'course_id', course_id)
        self._remove_from_table(cursor, CourseFieldsCache, 'course_id', course_id)

        if self.full_remove:
            print(f"------------ Remove StudentModuleHistory data for {course_id}")
            delete_sql = (f"DELETE FROM {StudentModuleHistory.objects.model._meta.db_table} WHERE student_module_id in ("
                          f"SELECT id from {StudentModule.objects.model._meta.db_table} WHERE course_id='{course_id}')")
            cursor.execute(delete_sql)

            print(f"------------ Remove StudentModule data for {course_id}")
            self._remove_from_table(cursor, StudentModule, 'course_id', course_id, use_chunks=True)

            print(f"------------ Remove TrackingLog data for {course_id}")
            self._remove_from_table(cursor, TrackingLog, 'course_id', course_id, use_chunks=True)

            print(f"------------ Remove CertificateGenerationHistory data for {course_id}")
            self._remove_from_table(cursor, CertificateGenerationHistory, 'course_id', course_id)

            print(f"------------ Remove GeneratedCertificate data for {course_id}")
            self._remove_from_table(cursor, GeneratedCertificate, 'course_id', course_id)

            print(f"------------ Remove PersistentSubsectionGradeOverride data for {course_id}")
            PersistentSubsectionGradeOverride.objects.filter(grade__course_id=course_key).delete()

            print(f"------------ Remove PersistentSubsectionGrade data for {course_id}")
            self._remove_from_table(cursor, PersistentSubsectionGrade, 'course_id', course_id)

            print(f"------------ Remove InstructorTask data for {course_id}")
            self._remove_from_table(cursor, InstructorTask, 'course_id', course_id)

            print(f"------------ Remove ManualEnrollmentAudit data for {course_id}")

            delete_subquery = f"SELECT id FROM {CourseEnrollment.objects.model._meta.db_table} WHERE course_id='{course_id}'"

            delete_sql = f"DELETE FROM {ManualEnrollmentAudit.objects.model._meta.db_table} WHERE enrollment_id in ({delete_subquery})"
            cursor.execute(delete_sql)

            delete_sql = (f"DELETE FROM {ScheduleExperience.objects.model._meta.db_table} WHERE schedule_id in "
                          f"(SELECT id from {Schedule.objects.model._meta.db_table} "
                          f"WHERE enrollment_id in ({delete_subquery}))")
            cursor.execute(delete_sql)

            delete_sql = f"DELETE FROM {Schedule.objects.model._meta.db_table} WHERE enrollment_id in ({delete_subquery})"
            cursor.execute(delete_sql)

            print(f"------------ Remove CourseEnrollmentAllowed data for {course_id}")
            self._remove_from_table(cursor, CourseEnrollmentAllowed, 'course_id', course_id)

            print(f"------------ Remove CourseEnrollment data for {course_id}")
            self._remove_from_table(cursor, CourseEnrollment, 'course_id', course_id, use_chunks=True)

            print(f"------------ Remove SequentialBlockAnswered data for {course_id}")
            self._remove_from_table(cursor, SequentialBlockAnswered, 'course_id', course_id, use_chunks=True)

            print(f"------------ Remove SequentialBlockAttempt data for {course_id}")
            self._remove_from_table(cursor, SequentialBlockAttempt, 'course_id', course_id, use_chunks=True)

            print(f"------------ Remove AttemptUserMigration data for {course_id}")
            self._remove_from_table(cursor, AttemptUserMigration, 'course_id', course_id)

            print(f"------------ Remove PropertiesInfo data for {course_id}")
            self._remove_from_table(cursor, PropertiesInfo, 'course_id', course_id)

            print(f"------------ Remove OraBlockScore data for {course_id}")
            self._remove_from_table(cursor, OraBlockScore, 'course_id', course_id)

            print(f"------------ Remove EnrollmentTrigger data for {course_id}")
            self._remove_from_table(cursor, EnrollmentTrigger, 'course_id', course_id)

            print(f"------------ Remove SplitModulestoreCourseIndex data for {course_id}")
            self._remove_from_table(cursor, SplitModulestoreCourseIndex, 'course_id', course_id)

            print(f"------------ Remove EnrollmentLog data for {course_id}")
            self._remove_from_table(cursor, EnrollmentLog, 'course_id', course_id)

            print(f"------------ Remove DBLogEntry data for {course_id}")
            self._remove_from_table(cursor, DBLogEntry, 'course_id', course_id)

            print(f"------------ Remove ProctoredExam data for {course_id}")
            delete_sql = f"DELETE FROM proctoring_proctoredexamhistory WHERE course_id='{course_id}'"
            cursor.execute(delete_sql)

            delete_sql = (f"DELETE FROM proctoring_proctoredexamstudentallowancehistory WHERE proctored_exam_id IN "
                          f"(SELECT id from {ProctoredExam.objects.model._meta.db_table} WHERE course_id='{course_id}')")
            cursor.execute(delete_sql)

            delete_sql = (f"DELETE FROM proctoring_proctoredexamstudentallowance WHERE proctored_exam_id IN "
                          f"(SELECT id from {ProctoredExam.objects.model._meta.db_table} WHERE course_id='{course_id}')")
            cursor.execute(delete_sql)

            delete_sql = (f"DELETE FROM proctoring_proctoredexamstudentattempt_history WHERE proctored_exam_id IN "
                          f"(SELECT id from {ProctoredExam.objects.model._meta.db_table} WHERE course_id='{course_id}')")
            cursor.execute(delete_sql)

            delete_sql = (f"DELETE FROM proctoring_proctoredexamstudentattempt WHERE proctored_exam_id IN "
                          f"(SELECT id from {ProctoredExam.objects.model._meta.db_table} WHERE course_id='{course_id}')")
            cursor.execute(delete_sql)

            self._remove_from_table(cursor, ProctoredExam, 'course_id', course_id)

            print(f"------------ Remove AnonymousUserId data for {course_id}")
            self._remove_from_table(cursor, AnonymousUserId, 'course_id', course_id)

            print(f"------------ Remove GradedAssignment data for {course_id}")
            self._remove_from_table(cursor, GradedAssignment, 'course_key', course_id, use_chunks=True)

            print(f"------------ Remove GradedAssignmentLti1p3 data for {course_id}")
            self._remove_from_table(cursor, GradedAssignmentLti1p3, 'course_key', course_id, use_chunks=True)

            print(f"------------ Remove Badgr Assertion data for {course_id}")
            self._remove_from_table(cursor, Assertion, 'course_id', course_id)

            print(f"------------ Remove BlockCompletion data for {course_id}")
            self._remove_from_table(cursor, BlockCompletion, 'course_key', course_id, use_chunks=True)

        if user_ids_to_remove:
            user_ids_to_remove_str = ",".join(f"{u_id}" for u_id in user_ids_to_remove)
            if self.full_remove:
                print(f"------------ Remove Users for {course_id}")
                self._remove_from_table(cursor, RefreshToken, 'user_id', user_ids_to_remove)
                self._remove_from_table(cursor, AccessToken, 'user_id', user_ids_to_remove)

                delete_subquery = f"SELECT id FROM {UserProfile.objects.model._meta.db_table} WHERE user_id IN ({user_ids_to_remove_str})"

                delete_sql = f"DELETE FROM {LanguageProficiency.objects.model._meta.db_table} WHERE user_profile_id in ({delete_subquery})"
                cursor.execute(delete_sql)

                delete_sql = f"DELETE FROM {SocialLink.objects.model._meta.db_table} WHERE user_profile_id in ({delete_subquery})"
                cursor.execute(delete_sql)

                delete_sql = f"DELETE FROM {UserPreference.objects.model._meta.db_table} WHERE user_id in ({user_ids_to_remove_str})"
                cursor.execute(delete_sql)

                cursor.execute("SET FOREIGN_KEY_CHECKS=0")
                self._remove_from_table(cursor, UserProfile, 'user_id', user_ids_to_remove)
                self._remove_from_table(cursor, User, 'id', user_ids_to_remove)
                cursor.execute("SET FOREIGN_KEY_CHECKS=1")
            else:
                print(f"------------ Deactivating Users for {course_id}")
                update_sql = (f"UPDATE auth_user SET "
                              f"email=CONCAT('deleted_{time.time()}_', id, '@deleted.net'), "
                              f"username=CONCAT('deleted_{time.time()}_', id), "
                              f"first_name='', "
                              f"last_name='', "
                              f"is_active=0 "
                              f"WHERE id IN ({user_ids_to_remove_str})")
                cursor.execute(update_sql)

        c2r.mysql_data_removed = True
        c2r.save()

        t2 = time.time()
        print(f"------------------------------------------ Remove data for {course_id} course --------- finish: "
              f"{t2 - t1} sec")

    def remove_mysql_courses_data(self):
        print("------------- Remove SiblingBlockUpdateTask items")
        SiblingBlockUpdateTask.objects.filter(Q(source_course_id__in=self.courses_ids) | Q(sibling_course_id__in=self.courses_ids)).delete()

        print("------------- Remove CredoModulesUserProfile items")
        CredoModulesUserProfile.objects.filter(course_id__in=self.courses_keys).delete()

        print("------------- Remove EnrollmentPropertiesPerCourse items")
        EnrollmentPropertiesPerCourse.objects.filter(course_id__in=self.courses_keys).delete()

        print("------------- Remove RegistrationPropertiesPerOrg items")
        RegistrationPropertiesPerOrg.objects.filter(org__in=self.orgs).delete()

        print("------------- Remove OrganizationTagOrder items")
        OrganizationTagOrder.objects.filter(org__org__in=self.orgs).delete()

        print("------------- Remove OrganizationTag items")
        OrganizationTag.objects.filter(org__org__in=self.orgs).delete()

        print("------------- Remove Organization items")
        Organization.objects.filter(org__in=self.orgs).delete()

        print("------------- Remove CourseExcludeInsights items")
        CourseExcludeInsights.objects.filter(course_id__in=self.courses_keys).delete()

        print("------------- Remove SendScores items")
        SendScores.objects.filter(course_id__in=self.courses_keys).delete()

        print("------------- Remove SiblingBlockNotUpdated items")
        SiblingBlockNotUpdated.objects.filter(source_course_id__in=self.courses_ids).delete()
        SiblingBlockNotUpdated.objects.filter(sibling_course_id__in=self.courses_ids).delete()

        print("------------- Remove SequentialViewedTask items")
        SequentialViewedTask.objects.filter(course_id__in=self.courses_keys).delete()

        print("------------- Remove CourseStaffExtended items")
        CourseStaffExtended.objects.filter(course_id__in=self.courses_keys).delete()

        print("------------- Remove AttemptCourseMigration items")
        AttemptCourseMigration.objects.filter(course_id__in=self.courses_ids).delete()

        print("------------- Remove SupervisorEvaluationInvitation items")
        SupervisorEvaluationInvitation.objects.filter(course_id__in=self.courses_ids).delete()

        print("------------- Remove DelayedTask items")
        DelayedTask.objects.filter(course_id__in=self.courses_ids).delete()

        print("------------- Remove OraBlockStructure items")
        OraBlockStructure.objects.filter(course_id__in=self.courses_ids).delete()

        print("------------- Remove TrackingLogUserInfo items for orgs")
        for org in self.orgs:
            print(f"------------- Remove TrackingLogUserInfo items for {org} org")
            TrackingLogUserInfo.objects.filter(org_id=org).delete()

        for i, course_id in enumerate(self.courses_ids):
            print(f"------------------------------------------ Process {course_id} course, {i+1}/{self.courses_num}")
            with connection.cursor() as cursor:
                self.remove_mysql_course_data(course_id, cursor)

    def remove_vertica_course_data(self, course_id):
        print(f"------------ Remove vertica data for {course_id} course")
        dsn = get_vertica_dsn()
        additional_settings = {}

        tables = [
            "api_course_structure_tags",
            "api_course_structure_tags_temp",
            "credo_modules_enrollmentlog",
            "credo_modules_enrollmentlog_temp",
            "credo_modules_trackinglog",
            "credo_modules_trackinglog_temp",
            "credo_modules_trackinglogprop",
            "credo_modules_trackinglogprop_temp",
            "credo_modules_usagelog",
            "credo_modules_usagelog_temp",
        ]

        with vertica_python.connect(dsn=dsn, **additional_settings) as vertica_conn:
            cursor = vertica_conn.cursor()

            for table in tables:
                sql = f"DELETE FROM {table} where course_id='{course_id}'";
                cursor.execute(sql)
                cursor.execute("COMMIT")

    def remove_vertica_courses_data(self):
        for course_id in self.courses_ids:
            c2r = CourseToRemove.objects.filter(course_id=course_id).first()
            if not c2r:
                raise Exception("CourseToRemove obj not found")
            if c2r.vertica_data_removed:
                continue

            self.remove_vertica_course_data(course_id)

            c2r.vertica_data_removed = True
            c2r.save()

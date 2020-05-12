from django.core.management import BaseCommand
from django.contrib.auth.models import User
from django.db.models import Q
from student.models import CourseAccessRole
from credo_modules.models import StaffUser


class Command(BaseCommand):

    def handle(self, *args, **options):
        items_to_insert = []

        StaffUser.objects.all().delete()

        course_access_roles = CourseAccessRole.objects.filter(
            role__in=('instructor', 'staff'), course_id__startswith='course-v1:')\
            .values('user_id', 'course_id').distinct()
        for v in course_access_roles:
            items_to_insert.append(StaffUser(user_id=v['user_id'], course_id=str(v['course_id'])))

        users = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        for user in users:
            items_to_insert.append(StaffUser(user_id=user.id))

        StaffUser.objects.bulk_create(items_to_insert)

from django.contrib.auth.models import User
from django.db import models


class InstructorAvailableSections(models.Model):
    """
    Enumerates list of tabs which could be switched off on Instructor Dashboard panel
    """
    user = models.OneToOneField(User, on_delete=models.SET_NULL, related_name='instructor_dashboard_tabs',
                                null=True, blank=True, verbose_name = 'Instructor')

    show_course_info = models.BooleanField(default=True, verbose_name = 'Show "Course Info" section')
    show_membership = models.BooleanField(default=True, verbose_name = 'Show "Membership" section')
    show_cohort = models.BooleanField(default=True, verbose_name = 'Show "Cohorts" section')
    show_student_admin = models.BooleanField(default=True, verbose_name = 'Show "Student Admin" section')
    show_data_download = models.BooleanField(default=True, verbose_name = 'Show "Data Download" section')
    show_email = models.BooleanField(default=True, verbose_name = 'Show "Email" section')
    show_analytics = models.BooleanField(default=True, verbose_name = 'Show "Analytics" section')
    show_certificates = models.BooleanField(default=True, verbose_name = 'Show "Certificates" section')
    show_studio_link = models.BooleanField(default=True, verbose_name = 'Show "View In Studio" link')

    class Meta:
        verbose_name = 'Instructor dashboard available sections'
        verbose_name_plural = 'Instructor dashboard available sections'

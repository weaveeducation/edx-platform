import json
import hashlib
from django.conf import settings
from django.urls import reverse
from common.djangoapps.credo_modules.models import Organization


def additional_profile_fields_hash(fields_json):
    fields_str = json.dumps(fields_json, sort_keys=True)
    return hashlib.md5(fields_str.encode('utf-8')).hexdigest()


def get_progress_page_url(course_key, student_id=None, default_progress_url=None):
    enable_extended_progress_page = False
    try:
        org = Organization.objects.get(org=course_key.org)
        if org.org_type is not None:
            enable_extended_progress_page = org.org_type.enable_extended_progress_page
    except Organization.DoesNotExist:
        pass

    if enable_extended_progress_page and settings.NW_COURSEWARE_MFE_ENABLED and settings.NW_COURSEWARE_MFE_URL:
        progress_url = settings.NW_COURSEWARE_MFE_URL + reverse('progress', kwargs={'course_id': str(course_key)})
        if student_id:
            progress_url = progress_url + '?userId=' + str(student_id)
    else:
        if default_progress_url:
            return default_progress_url
        if student_id:
            progress_url = reverse('student_progress', kwargs={
                'course_id': str(course_key), 'student_id': str(student_id)})
        else:
            progress_url = reverse('progress', kwargs={'course_id': str(course_key)})
    return progress_url

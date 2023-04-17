from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.views.decorators.http import require_POST
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from common.djangoapps.student.models import CourseEnrollment
from common.djangoapps.credo_modules.models import Organization, check_my_skills_access
from common.djangoapps.credo_modules.utils import get_skills_mfe_url
from common.djangoapps.edxmako.shortcuts import render_to_response
from common.djangoapps.myskills.views import api_tag_global_data, api_tag_section_data
from common.djangoapps.myskills.global_progress import get_tags_global_data, MAX_COURSES_PER_USER
from common.djangoapps.myskills.utils import convert_into_tree, get_student_name
from openedx.core.djangoapps.programs.models import ProgramsApiConfig


User = get_user_model()


def _get_global_skills_context(request, user_id, org):
    user = request.user
    additional_params = []
    student = user

    if user.is_superuser and user_id:
        student = User.objects.filter(id=user_id).first()
        if not student:
            raise Http404("Student not found")
        else:
            additional_params.append('user_id=' + user_id)
    else:
        user_id = None

    enrollments = CourseEnrollment.objects.filter(user=student, is_active=True)
    course_ids = []
    orgs = []

    for enroll in enrollments:
        if enroll.course_id.org not in orgs:
            orgs.append(enroll.course_id.org)

    orgs_access_extended_progress_page = [o.org for o in Organization.objects.filter(
        org__in=orgs, org_type__enable_extended_progress_page=True)]
    if org:
        if org in orgs_access_extended_progress_page:
            additional_params.append('org=' + org)
        else:
            org = None

    orgs = []

    for enroll in enrollments:
        enroll_org = enroll.course_id.org
        if enroll_org in orgs_access_extended_progress_page and (not org or org == enroll_org):
            course_ids.append(str(enroll.course_id))
            if enroll.course_id.org not in orgs:
                orgs.append(enroll.course_id.org)

    return user_id, student, course_ids, orgs, org, additional_params


@transaction.non_atomic_requests
@login_required
def global_skills_page(request):
    mfe_url = get_skills_mfe_url()
    if mfe_url and not request.user.is_superuser:
        return redirect(mfe_url + '/myskills')
    return render_global_skills_page(request)


def render_global_skills_page(request, display_in_frame=False):
    user_id = request.GET.get('user_id')
    org = request.GET.get('org')
    page = request.GET.get('page')
    group_tags = False

    is_frame = request.GET.get('frame')
    if is_frame:
        try:
            is_frame = int(is_frame)
            is_frame = is_frame == 1
        except ValueError:
            is_frame = None
    if not is_frame:
        is_frame = display_in_frame

    if page == 'skills':
        group_tags = True

    user_id, student, course_ids, orgs, org, additional_params = _get_global_skills_context(request, user_id, org)

    if is_frame:
        additional_params.append('frame=1')

    context = {
        'orgs': sorted(orgs),
        'course': None,
        'course_id': None,
        'assessments_display': False,
        'student_id': student.id,
        'student': student,
        'student_name': get_student_name(student),
        'current_url': reverse('global_skills'),
        'url_api_get_tag_data': reverse('global_skills_api_get_tag_data'),
        'url_api_get_tag_section_data': reverse('global_skills_api_get_tag_section_data'),
        'api_student_id': student.id,
        'api_org': org,
        'current_url_additional_params': '&'.join(additional_params) if additional_params else '',
        'show_dashboard_tabs': True,
        'show_program_listing': ProgramsApiConfig.is_enabled(),
        'show_my_skills': check_my_skills_access(request.user),
        'is_frame': is_frame,
    }

    if is_frame:
        context.update({
            'allow_iframing': True,
            'disable_accordion': True,
            'disable_header': True,
            'disable_footer': True,
            'disable_window_wrap': True,
            'disable_tabs': True
        })

    if len(course_ids) > MAX_COURSES_PER_USER and len(orgs) > 1 and not org:
        context.update({
            'current_url': reverse('global_skills') + (
                ('?' + '&'.join(additional_params)) if additional_params else '')
        })
        return render_to_response('courseware/extended_progress_choose_org.html', context)

    tags = get_tags_global_data(student, orgs, course_ids, group_tags=group_tags)
    if page == 'skills':
        tags_assessments = [v.copy() for v in tags if v['tag_is_last']]
        tags = convert_into_tree(tags)
        tags_assessments = sorted(tags_assessments, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))
        context.update({
            'tags': tags,
            'tags_assessments': tags_assessments
        })
        response = render_to_response('courseware/extended_progress_skills.html', context)
    else:
        tags_to_100 = sorted(tags, key=lambda k: "%03d_%s" % (k['percent_correct'], k['tag']))
        tags_from_100 = sorted(tags, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))
        context.update({
            'top5tags': tags_from_100[:5],
            'lowest5tags': tags_to_100[:5],
            'assessments': []
        })
        response = render_to_response('courseware/extended_progress.html', context)
    return response


@transaction.non_atomic_requests
@login_required
@require_POST
def api_get_global_tag_data(request):
    user_id = request.POST.get('student_id')
    tag = api_tag_global_data(request, user_id)

    return render_to_response('courseware/extended_progress_skills_tag_block.html', {
        'tag': tag
    })


@transaction.non_atomic_requests
@login_required
@require_POST
def api_get_global_tag_section_data(request):
    user_id = request.POST.get('student_id')
    items = api_tag_section_data(request, user_id)

    return render_to_response('courseware/extended_progress_skills_tag_section_block.html', {
        'items': items
    })

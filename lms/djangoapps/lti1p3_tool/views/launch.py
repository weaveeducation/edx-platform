import json
import logging

from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
from django.shortcuts import reverse
from django.views.decorators.http import require_POST
from opaque_keys.edx.keys import CourseKey

from lms.djangoapps.lti_provider.models import LTI1p3
from lms.djangoapps.lti_provider.users import update_lti_user_data
from lms.djangoapps.lti_provider.reset_progress import check_and_reset_lti_user_progress
from lms.djangoapps.lti_provider.views import enroll_user_to_course, render_courseware
from common.djangoapps.util.views import add_p3p_header
from common.djangoapps.credo_modules.models import check_and_save_enrollment_attributes, get_enrollment_attributes
from common.djangoapps.credo_modules.utils import get_skills_mfe_url
from common.djangoapps.edxmako.shortcuts import render_to_string
from mako.template import Template
from lms.djangoapps.courseware.courses import update_lms_course_usage
from lms.djangoapps.courseware.global_progress import render_global_skills_page
from lms.djangoapps.courseware.views.views import render_progress_page_frame
from lms.djangoapps.courseware.utils import get_lti_context_session_key

from .debug import render_launch_debug_page
from .deep_link import deep_link_course_launch
from .utils import (
    COURSE_PROGRESS_PAGE,
    DEBUG_PAGE,
    MY_SKILLS_PAGE,
    get_block_by_id,
    log_lti_launch,
    render_lti_error,
    update_graded_assignment,
)
from ..ext_courses import process_external_course
from ..tool_conf import ToolConfDb
from ..users import Lti1p3UserService
try:
    from pylti1p3.contrib.django import DjangoOIDCLogin, DjangoMessageLaunch, DjangoCacheDataStorage
    from pylti1p3.contrib.django.session import DjangoSessionService
    from pylti1p3.contrib.django.request import DjangoRequest
    from pylti1p3.deep_link_resource import DeepLinkResource
    from pylti1p3.exception import OIDCException, LtiException
    from pylti1p3.lineitem import LineItem
except ImportError:
    pass

log = logging.getLogger("edx.lti1p3_tool")


@csrf_exempt
@add_p3p_header
@xframe_options_exempt
@require_POST
def launch(request, usage_id=None):
    if not usage_id:
        usage_id = request.GET.get('block_id')
        course_id = request.GET.get('course_id')
        page = request.GET.get('page')

        if not usage_id and course_id:
            if page == COURSE_PROGRESS_PAGE:
                with transaction.atomic():
                    return _launch(request, course_id=course_id, page=page)
            else:
                return deep_link_course_launch(request, course_id)
        elif not usage_id and not course_id and page:
            with transaction.atomic():
                return _launch(request, page=page)

    block = None
    if usage_id:
        block, err_tpl = get_block_by_id(usage_id)
        if not block:
            return err_tpl

    with transaction.atomic():
        return _launch(request, block=block)


def _launch(request, block=None, course_id=None, page=None):
    tool_conf = ToolConfDb()
    jwt_data = None
    try:
        message_launch = DjangoMessageLaunch(request, tool_conf)
        message_launch.set_public_key_caching(DjangoCacheDataStorage(), cache_lifetime=7200)
        if page == DEBUG_PAGE:
            message_launch.validate_jwt_format()
            jwt_data = message_launch._jwt
        message_launch_data = message_launch.get_launch_data()

        state_params = message_launch.get_params_from_login()
        tool_conf = message_launch.get_tool_conf()
        iss = message_launch.get_iss()
        client_id = message_launch.get_client_id()
        lti_tool = tool_conf.get_lti_tool(iss, client_id)
    except LtiException as e:
        if page == DEBUG_PAGE:
            return render_launch_debug_page(request, jwt_data=jwt_data, error=str(e), http_error_code=403)
        return render_lti_error(str(e), 403)

    is_iframe = state_params.get('is_iframe') if state_params else True
    context_id = message_launch_data.get('https://purl.imsglobal.org/spec/lti/claim/context', {}).get('id')
    if context_id:
        context_id = context_id.strip()
    context_label = message_launch_data.get('https://purl.imsglobal.org/spec/lti/claim/context', {}).get('label')
    if context_label:
        context_label = context_label.strip()
    context_title = message_launch_data.get('https://purl.imsglobal.org/spec/lti/claim/context', {}).get('label')
    if context_title:
        context_title = context_title.strip()
    external_user_id = message_launch_data.get('sub')
    message_launch_custom_data = message_launch_data.get('https://purl.imsglobal.org/spec/lti/claim/custom', {})

    if block is None and course_id is None and page is None:
        cs_block_id = message_launch_custom_data.get("block_id")
        block, err_tpl = get_block_by_id(cs_block_id)
        if not block:
            return err_tpl

    course_key = None
    current_item = str(block.location) if block else str(page + '_page')
    if block:
        course_key = block.location.course_key
    elif course_id:
        course_key = CourseKey.from_string(course_id)
    usage_key = block.location if block else None

    if page == DEBUG_PAGE:
        return render_launch_debug_page(
            request, lti_tool=lti_tool, jwt_data=jwt_data,
        )

    lti_params = {}
    lti_email = message_launch_data.get('email', message_launch_custom_data.get('email'))
    if lti_email:
        lti_params['email'] = lti_email
    lti_first_name = message_launch_data.get('given_name')
    if lti_first_name:
        lti_params['first_name'] = lti_first_name
    lti_last_name = message_launch_data.get('family_name')
    if lti_last_name:
        lti_params['last_name'] = lti_last_name

    if lti_tool.use_names_and_role_provisioning_service and message_launch.has_nrps():
        members = message_launch.get_nrps().get_members()
        msg = "LTI 1.3 names and role provisioning service response: %s for block: %s" % (json.dumps(members),
                                                                                          current_item)
        log_lti_launch(request, 'names_and_roles', msg, iss, client_id, block_id=str(usage_key), user_id=None,
                       course_id=str(course_key), tool_id=lti_tool.id, page_name=page)

        for member in members:
            if str(member.get('user_id')) == str(external_user_id):
                member_email = member.get('email')
                if member_email and not lti_email:
                    lti_params['email'] = member_email
                member_given_name = member.get('given_name')
                if member_given_name and not lti_first_name:
                    lti_params['first_name'] = member_given_name
                member_family_name = member.get('family_name')
                if member_family_name and not lti_last_name:
                    lti_params['last_name'] = member_family_name

    us = Lti1p3UserService()
    lti_user = us.authenticate_lti_user(request, external_user_id, lti_tool, lti_params)

    request_params = message_launch_data.copy()
    request_params.update(message_launch_custom_data)

    enrollment_attributes = None
    if course_key:
        enrollment_attributes = get_enrollment_attributes(request_params, course_key,
                                                          context_label=context_label)

    if request.user.is_authenticated:
        roles = None
        lti_roles = message_launch_data.get('https://purl.imsglobal.org/spec/lti/claim/roles', None)\
            if lti_tool.allow_to_add_instructors_via_lti else None
        if lti_roles:
            roles = []
            for role in lti_roles:
                roles_lst = role.split('#')
                if len(roles_lst) > 1:
                    roles.append(roles_lst[1])

        if course_key:
            enroll_result = enroll_user_to_course(request.user, course_key, roles)
            if enroll_result:
                check_and_save_enrollment_attributes(enrollment_attributes, request.user, course_key)
        if lti_params and 'email' in lti_params:
            update_lti_user_data(request.user, lti_params['email'])

    msg = "LTI 1.3 JWT body: %s for block: %s" % (json.dumps(message_launch_data), current_item)
    log_user_id = request.user.id if request.user.is_authenticated else None
    log_lti_launch(request, 'launch', msg, iss, client_id, block_id=str(usage_key), user_id=log_user_id,
                   course_id=str(course_key), tool_id=lti_tool.id, page_name=page)

    ext_course = process_external_course(message_launch, str(course_key), context_id, lti_tool)
    us.update_external_enrollment(lti_user, ext_course, context_label=context_label, context_title=context_title)

    if block:
        if message_launch.has_ags():
            update_graded_assignment(request, lti_tool, message_launch, block, course_key, usage_key, request.user,
                                     external_user_id)
        else:
            log.error("LTI1.3 platform doesn't support assignments and grades service: %s" % lti_tool.issuer)

        # Reset attempts based on new context_ID:
        # https://credoeducation.atlassian.net/browse/DEV-209
        check_and_reset_lti_user_progress(context_id, enrollment_attributes, request.user, course_key, usage_key,
                                          lti_version=LTI1p3)

        if not is_iframe:
            if context_id:
                lti_context_id_key = get_lti_context_session_key(usage_key)
                request.session[lti_context_id_key] = context_id

            return HttpResponseRedirect(reverse('launch_new_tab', kwargs={
                'course_id': str(course_key),
                'usage_id': str(usage_key),
            }))

        update_lms_course_usage(request, usage_key, course_key)
        result = render_courseware(request, usage_key, lti_context_id=context_id)
        return result
    else:
        mfe_url = get_skills_mfe_url()
        if mfe_url:
            template = Template(render_to_string('static_templates/embedded_redirect.html', {
                'disable_accordion': True,
                'allow_iframing': True,
                'disable_header': True,
                'disable_footer': True,
                'disable_window_wrap': True,
                'page_type': page,
                'course_id': str(course_key) if course_key else '',
                'mfe_url': mfe_url
            }))
            return HttpResponse(template.render())

        if page == MY_SKILLS_PAGE:
            if not is_iframe:
                return HttpResponseRedirect(reverse('global_skills') + '?frame=1')
            return render_global_skills_page(request, display_in_frame=True)
        elif page == COURSE_PROGRESS_PAGE:
            if not is_iframe:
                return HttpResponseRedirect(reverse('progress', kwargs={'course_id': course_key}) + '?frame=1')
            return render_progress_page_frame(request, course_key)
        else:
            raise Http404()

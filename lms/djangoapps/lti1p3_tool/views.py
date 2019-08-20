import json
import logging
import hashlib
from urlparse import urlparse

from django.conf import settings
from django.http import HttpResponseBadRequest, HttpResponseForbidden, HttpResponse, HttpResponseNotFound,\
    HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import caches
from django.core.urlresolvers import reverse
from django.views.decorators.http import require_POST
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import UsageKey

from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from lti_provider.models import LTI1p3
from lti_provider.users import update_lti_user_data
from lti_provider.reset_progress import check_and_reset_lti_user_progress
from lti_provider.views import enroll_user_to_course, render_courseware
from util.views import add_p3p_header
from credo_modules.models import check_and_save_enrollment_attributes
from edxmako.shortcuts import render_to_string
from mako.template import Template
from courseware.courses import update_lms_course_usage
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError
from pylti1p3.exception import OIDCException, LtiException
from pylti1p3.lineitem import LineItem
from .oidc_login import ExtendedDjangoOIDCLogin
from .tool_conf import ToolConfDb
from .message_launch import ExtendedDjangoMessageLaunch
from .models import GradedAssignment
from .users import Lti1p3UserService
from .utils import get_lineitem_tag


log = logging.getLogger("edx.lti1p3_tool")


def get_block_by_id(block_id):
    try:
        if block_id:
            block_id = UsageKey.from_string(block_id)
    except InvalidKeyError:
        block_id = None

    if not block_id:
        return False, render_lti_error('Invalid URL', 400)
    else:
        try:
            block = modulestore().get_item(block_id)
            return block, False
        except ItemNotFoundError:
            return False, render_lti_error('Block not found', 404)


@csrf_exempt
@add_p3p_header
def login(request):
    if not settings.FEATURES['ENABLE_LTI_PROVIDER']:
        return HttpResponseForbidden()

    request_params, is_cached = get_params(request)

    target_link_uri = request_params.get('target_link_uri', request.GET.get('target_link_uri'))
    if not target_link_uri:
        return render_lti_error('Missing "target_link_uri" param', 400)

    passed_launch_url_obj = urlparse(target_link_uri)

    expected_launch_url = reverse('lti1p3_tool_launch')
    if expected_launch_url[-1] != '/':
        expected_launch_url += '/'
    if not passed_launch_url_obj.path.startswith(expected_launch_url):
        return render_lti_error('Invalid URL', 400)

    block_id = None
    passed_launch_url_path_items = [x for x in passed_launch_url_obj.path.split('/') if x]
    if len(passed_launch_url_path_items) > 2:
        block_id = passed_launch_url_path_items[2]
    else:
        for url_param in passed_launch_url_obj.query.split('&'):
            url_param_key, url_param_val = url_param.split('=')
            if url_param_key == 'block' or url_param_key == 'block_id':
                block_id = url_param_val
                break

    block, err_tpl = get_block_by_id(block_id)
    if not block:
        return err_tpl

    is_time_exam = getattr(block, 'is_proctored_exam', False) or getattr(block, 'is_time_limited', False)
    if not is_cached:
        cache = caches['default']
        json_params = json.dumps(request.POST)
        params_hash = hashlib.md5(json_params).hexdigest()
        cache_key = ':'.join([settings.EMBEDDED_CODE_CACHE_PREFIX, params_hash])
        cache.set(cache_key, json_params, settings.EMBEDDED_CODE_CACHE_TIMEOUT)
        template = Template(render_to_string('static_templates/embedded_new_tab.html', {
            'disable_accordion': True,
            'allow_iframing': True,
            'disable_header': True,
            'disable_footer': True,
            'disable_window_wrap': True,
            'hash': params_hash,
            'additional_url_params': request.META['QUERY_STRING'],
            'time_exam': 1 if is_time_exam else 0,
        }))
        return HttpResponse(template.render())

    tool_conf = ToolConfDb()
    oidc_login = ExtendedDjangoOIDCLogin(request, tool_conf, request_params)
    oidc_login.pass_params_to_launch({'is_iframe': request_params.get('iframe')})
    try:
        return oidc_login.redirect(target_link_uri)
    except OIDCException as e:
        return render_lti_error(str(e), 403)


@csrf_exempt
@add_p3p_header
@require_POST
def launch(request, usage_id=None):
    if not usage_id:
        usage_id = request.GET.get('block_id')

    block, err_tpl = get_block_by_id(usage_id)
    if not block:
        return err_tpl

    tool_conf = ToolConfDb()
    try:
        message_launch = ExtendedDjangoMessageLaunch(request, tool_conf)
        message_launch_data = message_launch.get_launch_data()
        state_params = message_launch.get_params_from_login()
        lti_tool = message_launch.get_lti_tool()
    except LtiException as e:
        return render_lti_error(str(e), 403)

    is_iframe = state_params.get('is_iframe') if state_params else True
    context_id = message_launch_data.get('https://purl.imsglobal.org/spec/lti/claim/context', {}).get('id')
    external_user_id = message_launch_data.get('sub')
    message_launch_custom_data = message_launch_data.get('https://purl.imsglobal.org/spec/lti/claim/custom', {})

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

    us = Lti1p3UserService()
    us.authenticate_lti_user(request, external_user_id, lti_tool, lti_params)

    course_key = block.location.course_key
    usage_key = block.location

    if request.user.is_authenticated:
        enroll_result = enroll_user_to_course(request.user, course_key)
        if enroll_result:
            request_params = message_launch_data.copy()
            request_params.update(message_launch_custom_data)
            check_and_save_enrollment_attributes(request_params, request.user, course_key)
        if lti_params and 'email' in lti_params:
            update_lti_user_data(request.user, lti_params['email'])

    if message_launch.has_ags():
        update_graded_assignment(lti_tool, message_launch, block, course_key, usage_key, request.user, external_user_id)
    else:
        log.error("LTI1.3 platform doesn't support assignments and grades service: %s" % lti_tool.issuer)

    # Reset attempts based on new context_ID:
    # https://credoeducation.atlassian.net/browse/DEV-209
    check_and_reset_lti_user_progress(context_id, request.user, course_key, usage_key, lti_version=LTI1p3)

    if not is_iframe:
        return HttpResponseRedirect(reverse('launch_new_tab', kwargs={
            'course_id': str(course_key),
            'usage_id': str(usage_key)
        }))

    update_lms_course_usage(request, usage_key, course_key)
    result = render_courseware(request, usage_key)
    return result


def get_params(request):
    """
    Getting params from request or from cache
    :param request: request
    :return: dictionary of params, flag: from cache or not
    """
    if request.GET.get('hash'):
        cache = caches['default']
        lti_hash = ':'.join([settings.EMBEDDED_CODE_CACHE_PREFIX, request.GET.get('hash')])
        cached = cache.get(lti_hash)
        if cached:
            cache.delete(lti_hash)
            log.info("Cached params: %s, request: %s" % (cached, request))
            request_params = json.loads(cached)
            request_params['iframe'] = request.GET.get('iframe', '0').lower() == '1'
            return request_params, True
    return request.POST, False


def render_lti_error(message, http_code=None):
    template = Template(render_to_string('static_templates/lti1p3_error.html', {
        'message': message,
        'http_code': http_code
    }))
    if http_code == 400:
        return HttpResponseBadRequest(template.render())
    elif http_code == 403:
        return HttpResponseForbidden(template.render())
    elif http_code == 404:
        return HttpResponseNotFound(template.render())
    return HttpResponse(template.render())


def update_graded_assignment(lti_tool, message_launch, block, course_key, usage_key, user, external_user_id):
    ags = message_launch.get_ags()
    message_launch_data = message_launch.get_launch_data()

    endpoint = message_launch_data.get('https://purl.imsglobal.org/spec/lti-ags/claim/endpoint', {})
    lineitem = endpoint.get('lineitem')
    if lineitem:
        try:
            GradedAssignment.objects.get(
                lti_lineitem=lineitem,
                lti_jwt_sub=external_user_id
            )
        except GradedAssignment.DoesNotExist:
            gr = GradedAssignment(
                user=user,
                course_key=course_key,
                usage_key=usage_key,
                lti_tool=lti_tool,
                lti_jwt_endpoint=endpoint,
                lti_jwt_sub=external_user_id,
                lti_lineitem=lineitem,
                lti_lineitem_tag=None,
                created_by_tool=False
            )
            gr.save()
    elif lti_tool.force_create_lineitem and block.graded:
        lti_lineitem_tag = get_lineitem_tag(usage_key)
        try:
            GradedAssignment.objects.get(
                lti_jwt_sub=external_user_id,
                lti_lineitem_tag=lti_lineitem_tag
            )
        except GradedAssignment.DoesNotExist:
            course = modulestore().get_course(course_key, depth=0)
            course_grade = CourseGradeFactory().read(user, course)
            earned, possible = course_grade.score_for_module(usage_key)

            line_item = LineItem()
            line_item.set_tag(lti_lineitem_tag) \
                .set_score_maximum(possible) \
                .set_label(block.display_name)
            line_item = ags.find_or_create_lineitem(line_item)
            gr = GradedAssignment(
                user=user,
                course_key=course_key,
                usage_key=usage_key,
                lti_tool=lti_tool,
                lti_jwt_endpoint=endpoint,
                lti_jwt_sub=external_user_id,
                lti_lineitem=line_item.get_id(),
                lti_lineitem_tag=lti_lineitem_tag,
                created_by_tool=True
            )
            gr.save()
    else:
        log.info("LTI1.3 platform didn't pass lineitem [issuer=%s, course_key=%s, usage_key=%s, user_id=%s]"
                 % (lti_tool.issuer, str(course_key), str(usage_key), str(user.id)))

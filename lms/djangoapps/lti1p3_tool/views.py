import json
import logging
import hashlib
import time
import platform
import datetime
from collections import OrderedDict
from urllib.parse import urlparse, unquote, quote, quote_plus

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, HttpResponse, HttpResponseNotFound,\
    HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.shortcuts import reverse
from django.views.decorators.http import require_POST
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey, UsageKey

from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from lms.djangoapps.lti_provider.models import LTI1p3
from lms.djangoapps.lti_provider.users import update_lti_user_data
from lms.djangoapps.lti_provider.reset_progress import check_and_reset_lti_user_progress
from lms.djangoapps.lti_provider.views import enroll_user_to_course, render_courseware, get_embedded_new_tab_page
from common.djangoapps.util.views import add_p3p_header
from common.djangoapps.credo_modules.models import check_and_save_enrollment_attributes, get_enrollment_attributes
from common.djangoapps.credo_modules.utils import get_skills_mfe_url
from common.djangoapps.edxmako.shortcuts import render_to_string
from mako.template import Template
from lms.djangoapps.courseware.courses import update_lms_course_usage
from lms.djangoapps.courseware.global_progress import render_global_skills_page
from lms.djangoapps.courseware.views.views import render_progress_page_frame
from lms.djangoapps.courseware.utils import get_lti_context_session_key
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError
from .ext_courses import process_external_course
from .tool_conf import ToolConfDb
from .models import GradedAssignment, LtiToolKey
from .users import Lti1p3UserService
from .utils import get_lineitem_tag
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
log_json = logging.getLogger("credo_json")

MY_SKILLS_PAGE = 'myskills'
COURSE_PROGRESS_PAGE = 'progress'
DEBUG_PAGE = 'debug'
ALLOWED_PAGES = [MY_SKILLS_PAGE, DEBUG_PAGE]


def get_block_by_id(block_id):
    try:
        if block_id:
            block_id = UsageKey.from_string(unquote(block_id))
    except InvalidKeyError:
        block_id = None

    if not block_id:
        return False, render_lti_error('Invalid URL: block ID is not set', 400)
    else:
        try:
            block = modulestore().get_item(block_id)
            return block, False
        except ItemNotFoundError:
            return False, render_lti_error('Block not found', 404)


def get_course_by_id(course_id):
    course_key = CourseKey.from_string(course_id)
    course = modulestore().get_course(course_key)
    if not course:
        return False, render_lti_error('Course not found', 404)
    return course, False


def get_course_tree(course):
    course_tree = []
    for chapter in course.get_children():
        if not chapter.visible_to_staff_only:
            item = {
                'id': str(chapter.location),
                'display_name': chapter.display_name,
                'children': [],
                'graded': False
            }
            for sequential in chapter.get_children():
                if len(sequential.get_children()) > 0:
                    graded_txt = "Graded" if sequential.graded else "Not Graded"
                    item['children'].append({
                        'id': str(sequential.location),
                        'display_name': str(sequential.display_name) + f" [{graded_txt}]",
                        'children': [],
                        'graded': sequential.graded
                    })
            if len(item['children']) > 0:
                course_tree.append(item)
    return course_tree


def get_course_sequential_blocks(course):
    items = {}
    for chapter in course.get_children():
        for sequential in chapter.get_children():
            if len(sequential.get_children()) > 0:
                items[str(sequential.location)] = {
                    'id': str(sequential.location),
                    'display_name': sequential.display_name,
                    'graded': sequential.graded
                }
    return items


def _get_request_header(request):
    headers = OrderedDict()
    if 'CONTENT_LENGTH' in request.META:
        headers['Content-Length'] = str(request.META['CONTENT_LENGTH'])
    if 'CONTENT_TYPE' in request.META:
        headers['Content-Type'] = str(request.META['CONTENT_TYPE'])
    for header, value in request.META.items():
        if not header.startswith('HTTP'):
            continue
        header = '-'.join([h.capitalize() for h in header[5:].lower().split('_')])
        headers[header] = str(value)
    return headers


def _render_login_debug_page(request, request_params=None, lti_tool=None, error=None, http_error_code=None,
                             login_redirect=None):
    headers = _get_request_header(request)
    get_data = OrderedDict()
    post_data = OrderedDict()
    for k, v in request.GET.items():
        get_data[k] = v
    for k, v in request.POST.items():
        post_data[k] = v

    login_params = None
    login_url = None
    if login_redirect:
        login_params_lst = ['iss', 'login_hint', 'target_link_uri', 'lti_message_hint',
                            'lti_deployment_id', 'client_id']

        login_params = {
            'skip_debug': '1'
        }
        for param_key in login_params_lst:
            if request.method == 'GET':
                param_value = request.GET.get(param_key)
            else:
                param_value = request.POST.get(param_key)
            if param_value:
                login_params[param_key] = param_value

        login_url = '/lti1p3_tool/login/?' + '&'.join([f"{k}={quote_plus(v)}" for k, v in login_params.items()])

    template = Template(render_to_string('static_templates/lti_1p3_login_debug.html', {
        'disable_accordion': True,
        'allow_iframing': True,
        'disable_header': True,
        'disable_footer': True,
        'disable_window_wrap': True,
        'request_path': request.path,
        'request_method': request.method,
        'headers_data': headers,
        'request_params': request_params,
        'get_data': get_data,
        'post_data': post_data,
        'lti_tool': lti_tool,
        'error': error,
        'http_error_code': http_error_code,
        'login_redirect': login_redirect,
        'login_url': login_url,
        'login_params': login_params,
    }))
    return HttpResponse(template.render())


def _render_launch_debug_page(request, lti_tool=None, jwt_data=None,
                              error=None, http_error_code=None):
    headers = _get_request_header(request)
    get_data = OrderedDict()
    post_data = OrderedDict()
    for k, v in request.GET.items():
        get_data[k] = v
    for k, v in request.POST.items():
        post_data[k] = v

    jwt_header = None
    jwt_body = None

    if jwt_data:
        jwt_header = json.dumps(jwt_data.get('header', {}), indent=4, sort_keys=True)
        jwt_body = json.dumps(jwt_data.get('body', {}), indent=4, sort_keys=True)

    template = Template(render_to_string('static_templates/lti_1p3_launch_debug.html', {
        'disable_accordion': True,
        'allow_iframing': True,
        'disable_header': True,
        'disable_footer': True,
        'disable_window_wrap': True,
        'request_path': request.path,
        'request_method': request.method,
        'headers_data': headers,
        'get_data': get_data,
        'post_data': post_data,
        'lti_tool': lti_tool,
        'jwt_header': jwt_header,
        'jwt_body': jwt_body,
        'error': error,
        'http_error_code': http_error_code,
    }))
    return HttpResponse(template.render())


@csrf_exempt
@add_p3p_header
@xframe_options_exempt
def login(request):
    if not settings.FEATURES['ENABLE_LTI_PROVIDER']:
        return HttpResponseForbidden()

    skip_debug = request.GET.get('skip_debug') == '1'
    request_params, is_cached = get_params(request)

    target_link_uri = request_params.get('target_link_uri', request.GET.get('target_link_uri'))
    if not target_link_uri:
        return render_lti_error('Missing "target_link_uri" param', 400)

    passed_launch_url_obj = urlparse(target_link_uri)

    expected_launch_url = reverse('lti1p3_tool_launch')
    if expected_launch_url[-1] != '/':
        expected_launch_url += '/'

    passed_launch_url_path = passed_launch_url_obj.path
    if passed_launch_url_path[-1] != '/':
        passed_launch_url_path += '/'

    if not passed_launch_url_path.startswith(expected_launch_url):
        return render_lti_error('Invalid URL', 400)

    block = None
    block_id = None
    course_id = None
    passed_launch_url_path_items = [x for x in passed_launch_url_obj.path.split('/') if x]
    page = None

    if len(passed_launch_url_path_items) > 2:
        block_id = passed_launch_url_path_items[2]
        if block_id == 'course':
            block_id = None
            if len(passed_launch_url_path_items) > 3:
                course_id = passed_launch_url_path_items[3]
        elif block_id in ALLOWED_PAGES:
            page = block_id
            block_id = None
    else:
        for url_param in passed_launch_url_obj.query.split('&'):
            if '=' in url_param:
                url_param_key, url_param_val = url_param.split('=')
                if url_param_key == 'block' or url_param_key == 'block_id':
                    block_id = url_param_val
                    break
                elif url_param_key == 'course_id':
                    course_id = unquote(url_param_val)
                elif url_param_key == 'page':
                    page = url_param_val

    if course_id:
        course, err_tpl = get_course_by_id(course_id)
        if not course:
            return err_tpl
    elif block_id:
        block, err_tpl = get_block_by_id(block_id)
        if not block:
            return err_tpl
    elif not page or page not in ALLOWED_PAGES:
        raise Http404()

    is_time_exam = False
    if block:
        is_time_exam = getattr(block, 'is_proctored_exam', False) or getattr(block, 'is_time_limited', False)

    if not is_cached and (page != DEBUG_PAGE or skip_debug):
        cache = caches['default']
        json_params = json.dumps(request.POST)
        params_hash = hashlib.md5(json_params.encode('utf-8')).hexdigest()
        cache_key = ':'.join([settings.EMBEDDED_CODE_CACHE_PREFIX, params_hash])
        cache.set(cache_key, json_params, settings.EMBEDDED_CODE_CACHE_TIMEOUT)
        template = get_embedded_new_tab_page(
            is_time_exam=is_time_exam, url_query=request.META['QUERY_STRING'], request_hash=params_hash)
        return HttpResponse(template.render())

    tool_conf = ToolConfDb()
    django_request = DjangoRequest(request, default_params=request_params)
    django_session = DjangoSessionService(request)
    oidc_login = DjangoOIDCLogin(django_request, tool_conf, session_service=django_session)
    oidc_login.pass_params_to_launch({'is_iframe': request_params.get('iframe')})

    iss = request_params.get('iss', request.GET.get('iss'))
    client_id = request_params.get('client_id', request.GET.get('client_id'))
    lti_tool = tool_conf.get_lti_tool(iss, client_id)
    log_lti_launch(request, "login", None, iss, client_id, block_id=block_id, course_id=course_id, tool_id=lti_tool.id,
                   page_name=page)

    try:
        ret = oidc_login.redirect(target_link_uri)
        if page == DEBUG_PAGE and not skip_debug:
            return _render_login_debug_page(request, request_params, lti_tool, login_redirect=ret.url)
        else:
            return ret
    except OIDCException as e:
        if page == DEBUG_PAGE and not skip_debug:
            return _render_login_debug_page(request, request_params, lti_tool, error=str(e), http_error_code=403)
        return render_lti_error(str(e), 403)
    except LtiException as e:
        if page == DEBUG_PAGE and not skip_debug:
            return _render_login_debug_page(request, request_params, lti_tool, error=str(e), http_error_code=403)
        return render_lti_error(str(e), 403)


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
                return _deep_link_launch(request, course_id)
        elif not usage_id and not course_id and page:
            with transaction.atomic():
                return _launch(request, page=page)

    block, err_tpl = get_block_by_id(usage_id)
    if not block:
        return err_tpl

    with transaction.atomic():
        return _launch(request, block)


@csrf_exempt
@add_p3p_header
@xframe_options_exempt
@require_POST
def progress(request, course_id):
    with transaction.atomic():
        return _launch(request, course_id=course_id, page=COURSE_PROGRESS_PAGE)


@csrf_exempt
@add_p3p_header
@xframe_options_exempt
@require_POST
def myskills(request):
    with transaction.atomic():
        return _launch(request, page=MY_SKILLS_PAGE)


@csrf_exempt
@add_p3p_header
@xframe_options_exempt
def debug_page(request):
    return _launch(request, page=DEBUG_PAGE)


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
            return _render_launch_debug_page(request, jwt_data=jwt_data, error=str(e), http_error_code=403)
        return render_lti_error(str(e), 403)

    course_key = None
    current_item = str(block.location) if block else str(page + '_page')
    if block:
        course_key = block.location.course_key
    elif course_id:
        course_key = CourseKey.from_string(course_id)
    usage_key = block.location if block else None

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

    if page == DEBUG_PAGE:
        return _render_launch_debug_page(
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


@csrf_exempt
@add_p3p_header
@require_POST
def launch_deep_link(request, course_id):
    return _deep_link_launch(request, course_id)


def _deep_link_launch(request, course_id):
    course_key = CourseKey.from_string(course_id)
    with modulestore().bulk_operations(course_key):
        course, err_tpl = get_course_by_id(course_id)
        if not course:
            return err_tpl

        tool_conf = ToolConfDb()
        try:
            message_launch = DjangoMessageLaunch(request, tool_conf)
            message_launch_data = message_launch.get_launch_data()
            iss = message_launch.get_iss()
            client_id = message_launch.get_client_id()
            lti_tool = tool_conf.get_lti_tool(iss, client_id)
        except LtiException as e:
            return render_lti_error(str(e), 403)

        msg = "LTI 1.3 JWT body: %s for course: %s [deep link usage]" \
              % (json.dumps(message_launch_data), str(course_id))
        log_lti_launch(request, 'deep_link_launch', msg, iss, client_id, block_id=None, user_id=None,
                       course_id=str(course_key), tool_id=lti_tool.id)

        is_deep_link_launch = message_launch.is_deep_link_launch()
        if not is_deep_link_launch:
            return render_lti_error('Must be Deep Link Launch', 400)

        deep_linking_settings = message_launch_data\
            .get('https://purl.imsglobal.org/spec/lti-dl/claim/deep_linking_settings', {})
        accept_types = deep_linking_settings.get('accept_types', [])
        if 'ltiResourceLink' not in accept_types:
            return render_lti_error("LTI Platform doesn't support ltiResourceLink type", 400)

        accept_multiple = deep_linking_settings.get('accept_multiple', False)

        course_tree = get_course_tree(course)
        if len(course_tree) == 0:
            return render_lti_error("There is no available content in the chosen course", 400)

        template = Template(render_to_string('static_templates/lti1p3_deep_link.html', {
            'disable_accordion': True,
            'allow_iframing': True,
            'disable_header': True,
            'disable_footer': True,
            'disable_window_wrap': True,
            'course_tree': course_tree,
            'section_title': course.display_name,
            'accept_multiple': accept_multiple,
            'launch_id': message_launch.get_launch_id(),
            'submit_url': reverse('lti1p3_tool_launch_deep_link_submit', kwargs={
                'course_id': course_id
            })
        }))
        return HttpResponse(template.render())


@csrf_exempt
@add_p3p_header
@require_POST
def launch_deep_link_submit(request, course_id):
    course_key = CourseKey.from_string(course_id)
    launch_id = request.POST.get('launch_id', '')
    auto_create_lineitem = request.POST.get('auto_create_lineitem') == '1'
    if not launch_id:
        return render_lti_error('Invalid launch id', 400)

    with modulestore().bulk_operations(course_key):
        course, err_tpl = get_course_by_id(course_id)
        if not course:
            return err_tpl

        course_items = get_course_sequential_blocks(course)

        tool_conf = ToolConfDb()
        message_launch = DjangoMessageLaunch.from_cache(launch_id, request, tool_conf)
        iss = message_launch.get_iss()
        client_id = message_launch.get_client_id()
        tool_conf = message_launch.get_tool_conf()

        if message_launch.check_jwt_body_is_empty():
            return render_lti_error('Session has expired. Please repeat request one more time.', 403)

        if not message_launch.is_deep_link_launch():
            return render_lti_error('Must be Deep Link Launch', 400)

        lti_tool = tool_conf.get_lti_tool(iss, client_id)
        message_launch_data = message_launch.get_launch_data()
        deep_linking_settings = message_launch_data \
            .get('https://purl.imsglobal.org/spec/lti-dl/claim/deep_linking_settings', {})
        accept_types = deep_linking_settings.get('accept_types', [])
        if 'ltiResourceLink' not in accept_types:
            return render_lti_error("LTI Platform doesn't support ltiResourceLink type", 400)

        accept_multiple = deep_linking_settings.get('accept_multiple', False)

        block_ids = []
        if accept_multiple:
            block_ids = request.POST.getlist('block_ids[]')
        else:
            passed_block_id = request.POST.get('block_id')
            if passed_block_id:
                block_ids.append(passed_block_id)

        course_grade = None
        if auto_create_lineitem:
            course_grade = CourseGradeFactory().read(AnonymousUser(), course)

        resources = []
        for block_id in block_ids:
            if block_id not in course_items:
                return render_lti_error('Invalid %s link' % block_id, 400)
            launch_url = reverse('lti1p3_tool_launch')
            if launch_url[-1] != '/':
                launch_url += '/'

            launch_url = request.build_absolute_uri(launch_url + '?block_id=' + quote(block_id))
            resource = DeepLinkResource()
            resource.set_url(launch_url) \
                .set_title(course_items[block_id]['display_name'])

            if auto_create_lineitem and course_items[block_id]['graded']:
                earned, possible = course_grade.score_for_module(UsageKey.from_string(block_id))
                line_item = LineItem()
                line_item.set_tag(get_lineitem_tag(block_id)) \
                    .set_score_maximum(possible) \
                    .set_label(course_items[block_id]['display_name'])
                resource.set_lineitem(line_item)

            resources.append(resource)

        if len(resources) == 0:
            return render_lti_error('There are no resources to submit', 400)

        deep_linking_service = message_launch.get_deep_link()
        message_jwt = deep_linking_service.get_message_jwt(resources)
        response_jwt = deep_linking_service.encode_jwt(message_jwt)

        msg = "LTI1.3 platform deep link jwt source message [issuer=%s, course_key=%s]: %s"\
              % (lti_tool.issuer, str(course_key), str(json.dumps(message_jwt)))
        log_lti_launch(request, 'deep_link_launch_submit', msg, iss, client_id, block_id=None, user_id=None,
                       course_id=str(course_key), tool_id=lti_tool.id)

        html = deep_linking_service.get_response_form_html(response_jwt)
        return HttpResponse(html)


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


def update_graded_assignment(request, lti_tool, message_launch, block, course_key, usage_key, user, external_user_id):
    ags = message_launch.get_ags()
    message_launch_data = message_launch.get_launch_data()
    iss = message_launch.get_iss()
    client_id = message_launch.get_client_id()

    endpoint = message_launch_data.get('https://purl.imsglobal.org/spec/lti-ags/claim/endpoint', {})
    lineitem = endpoint.get('lineitem')
    if lineitem:
        try:
            GradedAssignment.objects.get(
                lti_lineitem=lineitem,
                lti_jwt_sub=external_user_id,
                course_key=course_key,
                usage_key=usage_key,
                user=user,
            )
        except GradedAssignment.DoesNotExist:
            try:
                other_assignment = GradedAssignment.objects.get(
                    lti_lineitem=lineitem,
                    lti_jwt_sub=external_user_id,
                )
                postfix = '_' + str(int(time.time())) + '_disabled'
                other_assignment.lti_lineitem = other_assignment.lti_lineitem + postfix
                other_assignment.disabled = True
                other_assignment.save()
            except GradedAssignment.DoesNotExist:
                pass
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
        msg = "LTI1.3 platform didn't pass lineitem [issuer=%s, course_key=%s, usage_key=%s, user_id=%s]"\
              % (lti_tool.issuer, str(course_key), str(usage_key), str(user.id))
        log_lti_launch(request, 'launch', msg, iss, client_id, block_id=usage_key, user_id=user.id,
                       course_id=str(course_key), tool_id=lti_tool.id)


@csrf_exempt
def get_jwks(request, key_id):
    try:
        key = LtiToolKey.objects.get(id=key_id)
        return JsonResponse({'keys': [key.public_jwk]})
    except LtiToolKey.DoesNotExist:
        return HttpResponseBadRequest()


def log_lti_launch(request, action, message, iss, client_id, block_id=None, user_id=None, course_id=None,
                   tool_id=None, data=None, page_name=None):
    hostname = platform.node().split(".")[0]
    res = {
        'action': action,
        'type': 'lti_launch',
        'hostname': hostname,
        'datetime': str(datetime.datetime.now()),
        'timestamp': time.time(),
        'message': message if message else None,
        'iss': iss if iss else None,
        'client_id': client_id if client_id else None,
        'user_id': user_id,
        'block_id': str(block_id),
        'course_id': str(course_id),
        'client_ip': get_client_ip(request),
        'tool_id': tool_id if tool_id else None,
        'lti_version': '1.3'
    }
    if page_name:
        res['page_name'] = page_name
    if data:
        res.update(data)
    log_json.info(json.dumps(res))


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

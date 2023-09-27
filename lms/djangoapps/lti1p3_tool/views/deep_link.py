import json
from urllib.parse import quote

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import AnonymousUser
from django.shortcuts import reverse
from django.views.decorators.http import require_POST
from opaque_keys.edx.keys import CourseKey, UsageKey

from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from common.djangoapps.util.views import add_p3p_header
from common.djangoapps.edxmako.shortcuts import render_to_string
from mako.template import Template
from xmodule.modulestore.django import modulestore
from .utils import (
    get_course_by_id,
    get_course_sequential_blocks,
    get_course_tree,
    log_lti_launch,
    render_lti_error,
)
from ..tool_conf import ToolConfDb
from ..models import LtiDeepLink, LtiDeepLinkCourse
from ..utils import get_lineitem_tag
try:
    from pylti1p3.contrib.django import DjangoOIDCLogin, DjangoMessageLaunch, DjangoCacheDataStorage
    from pylti1p3.contrib.django.session import DjangoSessionService
    from pylti1p3.contrib.django.request import DjangoRequest
    from pylti1p3.deep_link_resource import DeepLinkResource
    from pylti1p3.exception import OIDCException, LtiException
    from pylti1p3.lineitem import LineItem
except ImportError:
    pass


@csrf_exempt
@add_p3p_header
@require_POST
def launch_course_deep_link(request, course_id):
    return deep_link_course_launch(request, course_id)


def deep_link_course_launch(request, course_id):
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

        template = Template(render_to_string('static_templates/lti1p3_deep_link_courses.html', {
            'disable_accordion': True,
            'allow_iframing': True,
            'disable_header': True,
            'disable_footer': True,
            'disable_window_wrap': True,
            'course_tree': course_tree,
            'section_title': course.display_name,
            'accept_multiple': accept_multiple,
            'launch_id': message_launch.get_launch_id(),
            'submit_url': reverse('lti1p3_tool_launch_course_deep_link_submit', kwargs={
                'course_id': course_id
            })
        }))
        return HttpResponse(template.render())


@csrf_exempt
@add_p3p_header
@require_POST
def launch_deep_link(request, token):
    tool_conf = ToolConfDb()
    try:
        message_launch = DjangoMessageLaunch(request, tool_conf)
        message_launch_data = message_launch.get_launch_data()
        iss = message_launch.get_iss()
        client_id = message_launch.get_client_id()
        lti_tool = tool_conf.get_lti_tool(iss, client_id)
    except LtiException as e:
        return render_lti_error(str(e), 403)

    dl_obj = LtiDeepLink.objects.filter(lti_tool=lti_tool, url_token=token, is_active=True).first()
    if not dl_obj:
        return render_lti_error("Deep Link object not found", 404)

    msg = "LTI 1.3 JWT body: %s for dl-token: %s [deep link usage]" \
          % (json.dumps(message_launch_data), str(token))
    log_lti_launch(request, 'deep_link_launch', msg, iss, client_id, block_id=None, user_id=None,
                   tool_id=lti_tool.id, dl_token=str(token))

    is_deep_link_launch = message_launch.is_deep_link_launch()
    if not is_deep_link_launch:
        return render_lti_error('Must be Deep Link Launch', 400)

    deep_linking_settings = message_launch_data \
        .get('https://purl.imsglobal.org/spec/lti-dl/claim/deep_linking_settings', {})
    accept_types = deep_linking_settings.get('accept_types', [])
    if 'ltiResourceLink' not in accept_types:
        return render_lti_error("LTI Platform doesn't support ltiResourceLink type", 400)

    accept_multiple = deep_linking_settings.get('accept_multiple', False)

    dl_courses = LtiDeepLinkCourse.objects.filter(lti_deep_link=dl_obj)

    course_tree_list = []

    for dl_course in dl_courses:
        with modulestore().bulk_operations(dl_course.course_key):
            course, err_tpl = get_course_by_id(str(dl_course.course_key))
            if not course:
                return err_tpl
            course_tree = get_course_tree(course)
            course_tree_list.append({
                "course_id": str(dl_course.course_key),
                "name": course.display_name,
                "course_tree": course_tree
            })

    template = Template(render_to_string('static_templates/lti1p3_deep_link.html', {
        'disable_accordion': True,
        'allow_iframing': True,
        'disable_header': True,
        'disable_footer': True,
        'disable_window_wrap': True,
        'course_tree_list': course_tree_list,
        'accept_multiple': accept_multiple,
        'launch_id': message_launch.get_launch_id(),
        'submit_url': reverse('lti1p3_tool_launch_deep_link_submit', kwargs={
            "token": str(token)
        })
    }))
    return HttpResponse(template.render())


@csrf_exempt
@add_p3p_header
@require_POST
def launch_deep_link_submit(request, token):
    launch_id = request.POST.get('launch_id', '')
    auto_create_lineitem = request.POST.get('auto_create_lineitem') == '1'
    if not launch_id:
        return render_lti_error('Invalid launch id', 400)

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

    dl_obj = LtiDeepLink.objects.filter(lti_tool=lti_tool, url_token=token, is_active=True).first()
    if not dl_obj:
        return render_lti_error("Deep Link object not found", 404)

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

    courses_cache = {}
    courses_items_cache = {}
    resources = []
    for block_id in block_ids:
        launch_url = reverse('lti1p3_tool_launch')
        if launch_url[-1] != '/':
            launch_url += '/'

        if lti_tool.deep_linking_short_launch_urls:
            launch_url = request.build_absolute_uri(launch_url)
        else:
            launch_url = request.build_absolute_uri(launch_url + '?block_id=' + quote(block_id))

        uk = UsageKey.from_string(block_id)
        course_key = uk.course_key
        course_id = str(course_key)
        if course_id not in courses_cache:
            course, err_tpl = get_course_by_id(course_id)
            courses_cache[course_id] = course
            course_items = get_course_sequential_blocks(course)
            courses_items_cache[course_id] = course_items
        else:
            course = courses_cache[course_id]
            course_items = courses_items_cache[course_id]

        course_grade = None
        if auto_create_lineitem:
            course_grade = CourseGradeFactory().read(AnonymousUser(), course)

        resource = DeepLinkResource()
        resource.set_url(launch_url) \
            .set_title(course_items[block_id]['display_name']) \
            .set_custom_params({"block_id": block_id})

        if auto_create_lineitem and course_items[block_id]['graded']:
            earned, possible = course_grade.score_for_block(UsageKey.from_string(block_id))
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

    msg = "LTI1.3 platform deep link jwt source message [issuer=%s, course_key=None]: %s" \
          % (lti_tool.issuer, str(json.dumps(message_jwt)))
    log_lti_launch(request, 'deep_link_launch_submit', msg, iss, client_id, block_id=None, user_id=None,
                   tool_id=lti_tool.id)

    html = deep_linking_service.get_response_form_html(response_jwt)
    return HttpResponse(html)


@csrf_exempt
@add_p3p_header
@require_POST
def launch_course_deep_link_submit(request, course_id):
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

            if lti_tool.deep_linking_short_launch_urls:
                launch_url = request.build_absolute_uri(launch_url)
            else:
                launch_url = request.build_absolute_uri(launch_url + '?block_id=' + quote(block_id))
            resource = DeepLinkResource()
            resource.set_url(launch_url) \
                .set_title(course_items[block_id]['display_name']) \
                .set_custom_params({"block_id": block_id})

            if auto_create_lineitem and course_items[block_id]['graded']:
                earned, possible = course_grade.score_for_block(UsageKey.from_string(block_id))
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

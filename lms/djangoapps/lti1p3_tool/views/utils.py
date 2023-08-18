import json
import logging
import time
import platform
import datetime
from collections import OrderedDict
from urllib.parse import unquote

from django.conf import settings
from django.http import HttpResponseBadRequest, HttpResponseForbidden, HttpResponse, HttpResponseNotFound
from django.core.cache import caches
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey, UsageKey

from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from common.djangoapps.edxmako.shortcuts import render_to_string
from mako.template import Template
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError
from ..models import GradedAssignment
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


def get_request_header(request):
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
            earned, possible = course_grade.score_for_block(usage_key)

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


def log_lti_launch(request, action, message, iss, client_id, block_id=None, user_id=None, course_id=None,
                   tool_id=None, data=None, page_name=None, dl_token=None):
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
        'dl_token': dl_token if dl_token else None,
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

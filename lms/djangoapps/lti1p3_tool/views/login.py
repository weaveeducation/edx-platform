import base64
import json
import hashlib
from urllib.parse import urlparse, unquote

from django.conf import settings
from django.http import Http404, HttpResponseForbidden, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
from django.core.cache import caches
from django.shortcuts import reverse

from lms.djangoapps.lti_provider.views import get_embedded_new_tab_page
from common.djangoapps.util.views import add_p3p_header

from .debug import render_login_debug_page
from .utils import (
    ALLOWED_PAGES,
    DEBUG_PAGE,
    get_block_by_id,
    get_course_by_id,
    get_params,
    log_lti_launch,
    render_lti_error,
)
from ..tool_conf import ToolConfDb
from ..models import LtiDeepLink

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
    dl_id = None
    passed_launch_url_path_items = [x for x in passed_launch_url_obj.path.split('/') if x]
    page = None

    if len(passed_launch_url_path_items) > 2:
        block_id = passed_launch_url_path_items[2]
        if block_id == 'course':
            block_id = None
            if len(passed_launch_url_path_items) > 3:
                course_id = passed_launch_url_path_items[3]
        elif block_id == 'dl':
            block_id = None
            if len(passed_launch_url_path_items) > 3:
                dl_id = passed_launch_url_path_items[3]
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
                elif url_param_key == 'dl':
                    dl_id = unquote(url_param_val)
                elif url_param_key == 'page':
                    page = url_param_val

    if course_id:
        course, err_tpl = get_course_by_id(course_id)
        if not course:
            return err_tpl

    elif page and page not in ALLOWED_PAGES:
        raise Http404()

    if not block_id:
        lti_message_hint = request_params.get('lti_message_hint', request.GET.get('lti_message_hint'))
        if lti_message_hint:
            try:
                lti_message_hint_str = base64.b64decode(lti_message_hint).decode('utf-8')
                lti_message_hint_dict = json.loads(lti_message_hint_str)
                if isinstance(lti_message_hint_dict, dict):
                    block_id = lti_message_hint_dict.get("customParams", {}).get("block_id")
            except:
                pass

    if block_id:
        block, err_tpl = get_block_by_id(block_id)
        if not block:
            return err_tpl

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

    if dl_id and not LtiDeepLink.objects.filter(lti_tool=lti_tool, url_token=dl_id, is_active=True).exists():
        raise Http404("Invalid DL token")

    log_lti_launch(request, "login", None, iss, client_id, block_id=block_id, course_id=course_id, tool_id=lti_tool.id,
                   page_name=page)

    try:
        ret = oidc_login.redirect(target_link_uri)
        if page == DEBUG_PAGE and not skip_debug:
            return render_login_debug_page(request, request_params, lti_tool, login_redirect=ret.url)
        else:
            return ret
    except OIDCException as e:
        if page == DEBUG_PAGE and not skip_debug:
            return render_login_debug_page(request, request_params, lti_tool, error=str(e), http_error_code=403)
        return render_lti_error(str(e), 403)
    except LtiException as e:
        if page == DEBUG_PAGE and not skip_debug:
            return render_login_debug_page(request, request_params, lti_tool, error=str(e), http_error_code=403)
        return render_lti_error(str(e), 403)

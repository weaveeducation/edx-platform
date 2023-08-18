import json
from collections import OrderedDict
from urllib.parse import quote_plus

from django.http import HttpResponse
from common.djangoapps.edxmako.shortcuts import render_to_string
from mako.template import Template
from .utils import get_request_header

try:
    from pylti1p3.contrib.django import DjangoOIDCLogin, DjangoMessageLaunch, DjangoCacheDataStorage
    from pylti1p3.contrib.django.session import DjangoSessionService
    from pylti1p3.contrib.django.request import DjangoRequest
    from pylti1p3.deep_link_resource import DeepLinkResource
    from pylti1p3.exception import OIDCException, LtiException
    from pylti1p3.lineitem import LineItem
except ImportError:
    pass


def render_login_debug_page(request, request_params=None, lti_tool=None, error=None, http_error_code=None,
                            login_redirect=None):
    headers = get_request_header(request)
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


def render_launch_debug_page(request, lti_tool=None, jwt_data=None,
                             error=None, http_error_code=None):
    headers = get_request_header(request)
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

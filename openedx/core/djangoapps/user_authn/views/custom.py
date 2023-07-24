import json
import logging
import uuid
import platform
import datetime
import time
import jwt


from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth import login as django_login
from django.shortcuts import redirect
from common.djangoapps.student.models import UserProfile, CourseEnrollment
from common.djangoapps.credo.auth_helper import CredoIpHelper
from common.djangoapps.credo.api_client import ApiRequestError
from common.djangoapps.credo_modules.models import update_unique_user_id_cookie
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from urllib.parse import parse_qs, urlparse


User = get_user_model()
log = logging.getLogger("edx.student")
log_json = logging.getLogger("credo_json")


def register_login_and_enroll_anonymous_user(request, course_key, redirect_to=None, email_domain=None):
    created = False
    edx_username = None
    edx_password = None
    edx_user = None
    if email_domain is None:
        email_domain = 'credomodules.com'

    while not created:
        edx_username = str(uuid.uuid4())[0:30]
        edx_password = str(uuid.uuid4())
        edx_email = '%s@%s' % (edx_username, email_domain)

        try:
            with transaction.atomic():
                edx_user = User.objects.create_user(
                    username=edx_username,
                    password=edx_password,
                    email=edx_email,
                )
                edx_user_profile = UserProfile(user=edx_user)
                edx_user_profile.save()
            created = True
        except IntegrityError:
            # The random edx_user_id wasn't unique. Since 'created' is still
            # False, we will retry with a different random ID.
            pass

    edx_user_auth = authenticate(
        username=edx_username,
        password=edx_password,
    )
    if not edx_user_auth:
        # This shouldn't happen, since we've created edX accounts for any LTI
        # users by this point, but just in case we can return a 403.
        raise PermissionDenied()
    django_login(request, edx_user_auth)
    CourseEnrollment.enroll(edx_user, course_key)
    request.session.set_expiry(0)

    if redirect_to:
        return redirect(redirect_to)
    else:
        update_unique_user_id_cookie(request)
        return edx_user


def validate_credo_access(request, redirect_to=None):
    jwt_auth_success = False
    jwt_auth_error = ''
    jwt_data = None
    jwt_secret = settings.CREDO_API_CONFIG.get('jwt_secret', None)
    jwt_token = request.GET.get('jwt_token', None)

    try:
        if not jwt_token and redirect_to and '?' in redirect_to:
            next_args = parse_qs(urlparse(redirect_to).query)
            if 'jwt_token' in next_args:
                jwt_token = next_args['jwt_token'][0]
    except (KeyError, ValueError, IndexError):
        pass

    course_id = None
    path = request.path
    path_data = path.split('/')
    if len(path_data) > 2:
        course_id = path_data[2]

    user_ip = request.META.get('REMOTE_ADDR', None)
    headers = {
        'HTTP_X_FORWARDED_FOR': request.META.get('HTTP_X_FORWARDED_FOR', None),
        'HTTP_HOST': request.META.get('HTTP_HOST', None),
        'HTTP_REFERER': request.META.get('HTTP_REFERER', None)
    }
    api_ip_response = None
    api_referrer_response = None
    auth_success = False
    ip_param_passed_to_api = None
    referrer_param_passed_to_api = None
    referrer_taken_from = None

    if jwt_token:
        try:
            jwt_data = jwt.decode(jwt_token, jwt_secret, algorithms=['HS256', 'RS256'], leeway=60)
            if isinstance(jwt_data, dict) and 'client_id' in jwt_data and jwt_data['client_id']:
                log.info('Successfully authentication with jwt token (%s): %s', str(jwt_token), str(jwt_data))
                jwt_auth_success = True
                auth_success = True
            else:
                jwt_auth_error = 'Unsuccessfully authentication with jwt token (%s): %s' % (jwt_token, str(jwt_data))
                log.info(jwt_auth_error)
        except jwt.DecodeError:
            jwt_auth_error = 'Unsuccessfully authentication with jwt token (%s): decode error' % jwt_token
            log.info(jwt_auth_error)

    if not jwt_auth_success:
        ip_helper = CredoIpHelper()

        try:
            res, ip_param_passed_to_api = ip_helper.authenticate_by_ip_address(request)
            log.info('Authenticate by ip address: %s', str(res))
            if res:
                api_ip_response = res.copy()

            if not res or ('data' not in res) or ('data' in res and not res['data']):
                res, referrer_param_passed_to_api, referrer_taken_from = ip_helper.authenticate_by_referrer(request)
                log.info('Authenticate by referrer: %s', str(res))
                if res:
                    api_referrer_response = res.copy()

            if res and 'data' in res and res['data']:
                auth_success = True
        except ApiRequestError as e:
            msg = 'Validate Credo Access: ApiRequestError raised (HTTP code: %s, Message: %s)' % (
            e.http_code, e.http_msg)
            if not api_ip_response:
                api_ip_response = msg
            else:
                api_referrer_response = msg
            log.info(msg)

    log_credo_access(course_id, user_ip, headers, ip_param_passed_to_api, referrer_param_passed_to_api,
                     referrer_taken_from, api_ip_response, api_referrer_response, auth_success,
                     jwt_auth_success, jwt_auth_error, jwt_token, jwt_data)

    return auth_success


def log_credo_access(course_id, user_ip, headers, ip_param_passed_to_api, referrer_param_passed_to_api,
                     referrer_taken_from, api_ip_response, api_referrer_response, auth_success,
                     jwt_auth_success, jwt_auth_error, jwt_token, jwt_data, **kwargs):
    hostname = platform.node().split(".")[0]
    data = {
        'type': 'modules_auth',
        'hostname': hostname,
        'datetime': str(datetime.datetime.now()),
        'timestamp': time.time(),
        'course_id': str(course_id),
        'user_ip': user_ip,
        'ip_param_passed_to_api': ip_param_passed_to_api,
        'referrer_param_passed_to_api': referrer_param_passed_to_api,
        'referrer_taken_from': referrer_taken_from,
        'api_ip_response': str(api_ip_response) if api_ip_response else None,
        'api_referrer_response': str(api_referrer_response) if api_referrer_response else None,
        'auth_success': auth_success,
        'jwt_auth_success': jwt_auth_success,
        'jwt_auth_error': jwt_auth_error,
        'jwt_token': jwt_token,
        'jwt_data': str(jwt_data) if jwt_data else None
    }
    for k, v in headers.items():
        data['header_' + k.lower()] = v
    data.update(kwargs)
    log_json.info(json.dumps(data))

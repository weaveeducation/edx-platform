import json
from django.core.cache import caches
from pylti1p3.contrib.django.request import DjangoRequest
from pylti1p3.contrib.django.session import DjangoSessionService
from pylti1p3.message_launch import MessageLaunch
from .cookie_service import ExtendedDjangoCookieService


class ExtendedDjangoMessageLaunch(MessageLaunch):
    _public_key_prefix = 'lti1p3_key_set_url'
    _timeout = 7200  # 2 hrs

    def __init__(self, request, tool_config, session_service=None, cookie_service=None):
        django_request = DjangoRequest(request, post_only=True)
        cookie_service = cookie_service if cookie_service else ExtendedDjangoCookieService(django_request)
        session_service = session_service if session_service else DjangoSessionService(request)
        super(ExtendedDjangoMessageLaunch, self).__init__(django_request, tool_config, session_service, cookie_service)

    def _get_request_param(self, key):
        return self._request.get_param(key)

    def get_lti_tool(self):
        iss = self._get_iss()
        return self._tool_config.get_lti_tool(iss)

    def fetch_public_key(self, key_set_url):
        cache = caches['default']
        lti_hash = ':'.join([self._public_key_prefix, key_set_url])
        cached = cache.get(lti_hash)
        if cached:
            return json.loads(cached)
        else:
            public_key_set = super(ExtendedDjangoMessageLaunch, self).fetch_public_key(key_set_url)
            cache.set(lti_hash, json.dumps(public_key_set), self._timeout)
            return public_key_set

    def jwt_body_is_empty(self):
        jwt_body = self._get_jwt_body()
        return False if jwt_body else True

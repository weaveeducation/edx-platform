from pylti1p3.contrib.django.cookie import DjangoCookieService
from pylti1p3.contrib.django.redirect import DjangoRedirect
from pylti1p3.contrib.django.session import DjangoSessionService
from pylti1p3.oidc_login import OIDCLogin
from pylti1p3.request import Request


class DjangoRequest(Request):
    _request = None
    _post_only = False
    _additional_params = None

    def __init__(self, request, additional_params, post_only=False):
        self.set_request(request)
        self._post_only = post_only
        self._additional_params = additional_params

    def set_request(self, request):
        self._request = request

    def get_param(self, key):
        if self._post_only:
            return self._request.POST.get(key, self._additional_params.get(key))
        return self._request.GET.get(key, self._request.POST.get(key, self._additional_params.get(key)))

    def get_cookie(self, key):
        return self._request.COOKIES.get(key)


class ExtendedDjangoOIDCLogin(OIDCLogin):

    def __init__(self, request, tool_config, additional_params, session_service=None, cookie_service=None):
        django_request = DjangoRequest(request, additional_params)
        cookie_service = cookie_service if cookie_service else DjangoCookieService(django_request)
        session_service = session_service if session_service else DjangoSessionService(request)
        super(ExtendedDjangoOIDCLogin, self).__init__(django_request, tool_config, session_service, cookie_service)

    def get_redirect(self, url):
        return DjangoRedirect(url, self._cookie_service)

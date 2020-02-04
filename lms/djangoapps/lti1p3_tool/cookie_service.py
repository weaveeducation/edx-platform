from django.conf import settings
from pylti1p3.contrib.django.cookie import DjangoCookieService


class ExtendedDjangoCookieService(DjangoCookieService):

    def update_response(self, response):
        if self._cookie_data_to_set:
            session_cookie_secure = getattr(settings, 'SESSION_COOKIE_SECURE', False)
            response.set_cookie(
                self._cookie_data_to_set['key'],
                self._cookie_data_to_set['value'],
                max_age=self._cookie_data_to_set['exp'],
                path='/',
                secure=session_cookie_secure
            )

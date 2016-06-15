import logging

from credo.api_client import ApiClient
from django.conf import settings
from urlparse import urlparse


log = logging.getLogger("edx.credo.api_helper")


class CredoIpHelper(object):

    _client = None

    def __init__(self):
        domain = settings.CREDO_API_CONFIG.get('domain', None)
        client_key = settings.CREDO_API_CONFIG.get('client_key', None)
        client_secret = settings.CREDO_API_CONFIG.get('client_secret', None)
        secure = settings.CREDO_API_CONFIG.get('secure', False)
        self._client = ApiClient(domain=domain, secure=secure,
                                 client_key=client_key, client_secret=client_secret)

    def _get_api_client(self):
        return self._client

    def authenticate_by_ip_address(self, request):
        api_client = self._get_api_client()

        header_name = 'REMOTE_ADDR'
        ip = request.META.get('REMOTE_ADDR', None)
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', None)

        if x_forwarded_for:
            header_name = 'HTTP_X_FORWARDED_FOR'
            ip = x_forwarded_for
        if ip:
            ip_list = [i.strip() for i in ip.split(',')]
            ip_param = ','.join(ip_list)
            result = api_client.authenticate_ip(ip_param, {})
            log.info(u'authenticate_ip API answered %s for IP %s (from %s header)'
                     % (str(result), ip_param, header_name))
            return result

        return False

    def authenticate_by_referrer(self, request):
        taken_from = 'request'
        referer_url = get_request_referer_from_other_domain(request)

        if not referer_url:
            taken_from = 'cookie'
            referer_url = get_saved_referer(request)

        if referer_url:
            api_client = self._get_api_client()
            parsed_referer_uri = urlparse(referer_url)
            referer = 'http://%s' % parsed_referer_uri.netloc

            result = api_client.authenticate_referrer(referer)
            log.info(u'authenticate_referrer API answered %s for referer %s taken from %s'
                     % (str(result), referer, taken_from))
            return result

        log.info(u'Referer is not defined')
        return False

    def get_institution_by_id(self, ident):
        api_client = self._get_api_client()
        return api_client.get_institution_by_id(ident, {})


def get_request_referer_from_other_domain(request):

    host_domain = request.META.get('HTTP_HOST', None)
    referer_url = request.META.get('HTTP_REFERER', None)

    if host_domain and referer_url:
        parsed_referer_uri = urlparse(referer_url)
        referer_domain = parsed_referer_uri.netloc
        if referer_domain != host_domain:
            return referer_url

    return False


def get_saved_referer(request):
    return request.COOKIES.get('CREDO_HTTP_REFERER', None)


def save_referer(response, referer_url):
    response.set_cookie('CREDO_HTTP_REFERER', referer_url)

import time
import json
import requests


class ApiConnectionError(Exception):
    pass


class ApiRequestError(Exception):
    def __init__(self, http_msg=None, http_code=None):
        self.http_msg = http_msg
        self.http_code = http_code


class ApiClient(object):
    _secure = False
    _domain = 'localhost'
    _uri_prefix = '/api/v2'
    _token = None
    _user_agent = 'edx-platform-api-client'

    def __init__(self, domain=None, secure=False, token=None):
        self._secure = secure
        if domain:
            self._domain = domain
        if token:
            self._token = token

    def _get_url(self, path):
        protocol = 'https' if self._secure else 'http'
        url = '%s://%s' % (protocol, self._domain)
        if not path.startswith('/'):
            path = '/%s' % path
        return ''.join([url, self._uri_prefix, path])

    def _make_request(self, url, params):
        try:
            r = requests.get(url, params=params, headers={
                'authorization': 'Token ' + str(self._token),
                'content-type': 'application/vnd.api+json',
                'user-agent': self._user_agent,
            })
        except Exception as e:
            raise ApiConnectionError(e)

        try:
            response_date = r.json()
        except ValueError:
            raise ApiRequestError(r.text, r.status_code)

        return response_date

    def request(self, path, params=None):
        url = self._get_url(path)

        for k, v in params.iteritems():
            if not isinstance(v, (basestring, list)):
                params[k] = json.dumps(v)

        return self._make_request(url, params)

    def authenticate_ip(self, ip_param):
        return self.request('/clients', {'filter[ip]': ip_param})

    def authenticate_referrer(self, url):
        return self.request('/clients', {'filter[referrer]': url})

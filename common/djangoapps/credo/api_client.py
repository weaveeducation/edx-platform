import time
import json
import requests


class ApiConnectionError(Exception):
    pass


class ApiRequestError(Exception):
    def __init__(self, http_msg=None, http_code=None):
        self.http_msg = http_msg
        self.http_code = http_code


class ApiCache(object):
    _cache = None

    def __init__(self):
        self._cache = {}

    def clear(self, name):
        if name in self._cache:
            del self._cache[name]

    def get(self, name):
        if name in self._cache:
            return self._cache[name]
        return False

    def set(self, name, value):
        self._cache[name] = value


class ApiClient(object):
    _secure = False
    _domain = 'localhost'
    _uri_prefix = '/v1'
    _cache_prefix = 'credo:api:'
    _cache = None

    _oauth_token = None
    _oauth_token_cache = None

    _oauth_client_key = ''
    _oauth_client_secret = ''
    _oauth_token_path = '/oauth/token'

    _user_agent = 'edx-platform-api-client'

    def __init__(self, domain=None, secure=False, client_key=None, client_secret=None, cache=None):
        self._secure = secure
        if domain:
            self._domain = domain
        if client_key:
            self._oauth_client_key = client_key
        if client_secret:
            self._oauth_client_secret = client_secret
        self._cache = cache if cache else ApiCache()

    def _get_url(self, path):
        protocol = 'https' if self._secure else 'http'
        url = '%s://%s' % (protocol, self._domain)
        if not path.startswith('/'):
            path = '/%s' % path
        return ''.join([url, self._uri_prefix, path])

    def _make_request(self, url, params):
        try:
            r = requests.get(url, params=params, headers={'user-agent': self._user_agent})
        except Exception as e:
            raise ApiConnectionError(e)

        try:
            response_date = r.json()
        except ValueError:
            raise ApiRequestError(r.text, r.status_code)

        return response_date

    def _make_oauth_request(self, url, params):
        if 'access_token' not in params:
            params['access_token'] = self._get_access_token()

        for k, v in params.iteritems():
            if not isinstance(v, basestring):
                params[k] = json.dumps(v)

        return self._make_request(url, params)

    def request(self, path, params=None, cachable=True):
        # if response has been cached, return cached response
        response = self._get_cached_response(path)
        if response:
            return response

        # response has not been cached; make a new request to API
        response = self._make_oauth_request(self._get_url(path), params)

        if cachable:
            self._cache_response(path, response)

        return response

    def _get_cached_response(self, path):
        return self._cache.get(''.join([self._cache_prefix, path]))

    def _cache_response(self, path, response):
        self._cache.set(''.join([self._cache_prefix, path]), response)

    def _get_access_token(self):
        if self._oauth_token is not None:
            return self._oauth_token

        if ApiClient._oauth_token_cache and time.time() < ApiClient._oauth_token_cache['expires']:
            return ApiClient._oauth_token_cache['access_token']

        start_time = time.time()
        reduce_expires_cache = 60

        token_data = self._get_application_token()
        token_data['expires'] = start_time + int(token_data['expires_in']) - reduce_expires_cache

        ApiClient._oauth_token_cache = token_data

        self._oauth_token = token_data['access_token']
        return self._oauth_token

    def _get_application_token(self):
        token_params = {
            'grant_type': 'client_credentials',
            'client_id': self._oauth_client_key,
            'client_secret': self._oauth_client_secret
        }

        token_url = self._get_url(self._oauth_token_path)
        return self._make_request(token_url, token_params)

    def _refresh_application_token(self, refresh_token):
        token_params = {
            'grant_type': 'refresh_token',
            'client_id': self._oauth_client_key,
            'client_secret': self._oauth_client_secret,
            'refresh_token': refresh_token
        }
        token_url = self._get_url(self._oauth_token_path)
        return self._make_request(token_url, token_params)

    # user shortcut methods
    def get_institution_by_id(self, ident, params):
        return self.request('/user/institution/%s' % ident, params)

    def get_institution_customizations(self, ident, params):
        return self.request('/user/institution/%s/customizations' % ident, params)

    def authenticate_user(self, username, password, params):
        return self.request('/user/institution/email/%s/password/%s' % (username, password), params)

    def authenticate_ip(self, ip, params):
        return self.request('/user/institution/ip/%s' % ip, params)

    def authenticate_referrer(self, url, institution_id=None, params=None):
        if params is None:
            params = {}
        params['referrer'] = url
        if institution_id:
            params['institutionId'] = institution_id
        return self.request('/user/institution/referrer', params)

    def encrypt(self, data, params=None):
        if params is None:
            params = {}
        params['string'] = data
        return self.request('/user/utils/encrypt', params)

    def decrypt(self, data, params=None):
        if params is None:
            params = {}
        params['string'] = data
        return self.request('/user/utils/decrypt', params)

    # content shortcut methods
    def get_titles(self, params):
        return self.request('/content/title', params)

    def get_title_categories(self, params):
        return self.request('/content/title/browse/category', params)

    def get_titles_by_category_name(self, name, params):
        return self.request('/content/title/browse/category/%s' % name, params)

    def get_categories(self, params):
        return self.request('/content/category', params)

    def get_category(self, category, params):
        return self.request('/content/category/%s' % category, params)

    def get_entries_by_name(self, title, entry, params):
        return self.request('/content/entry/%s/%s' % (title, entry), params)

    def get_entry(self, title, entry, ident, params):
        return self.request('/content/entry/%s/%s/%s' % (title, entry, ident), params)

    def get_entry_body(self, title, entry, ident, params):
        return self.request('/content/body/%s/%s/%s' % (title, entry, ident), params)

    def get_entry_citation(self, title, entry, ident, format, params):
        return self.request('/content/citation/%s/%s/%s/%s' % (format, title, entry, ident))

    def get_entry_related_content(self, tp, title, entry, ident, params):
        # tp: entry, image, audio, video, location
        return self.request('/content/entry/related/%s/%s/%s/%s' % (tp, title, entry, ident), params)

    def get_content_by_title(self, tp, title, params):
        # tp: entry, image, audio, video, person, location, category, publisher, topic
        uri = '/content/%s' % tp
        if tp == 'category' or tp == 'publisher':
            uri = '%s/title' % uri
        return self.request('/'.join([uri, title]), params)

    # search shortcut methods
    def search_topics(self, term, params):
        return self.request('/search/topic/%s' % term, params)

    def search_topics_advanced(self, params):
        return self.request('/search/topic/advanced/', params)

    def search_entries_advanced(self, params):
        return self.request('/search/advanced/', params)

    def search_entries(self, term, params):
        return self.request('/search/all/%s' % term, params)

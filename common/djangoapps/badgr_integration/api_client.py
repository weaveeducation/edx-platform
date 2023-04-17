import requests
from enum import Enum
from datetime import timedelta
from django.utils import timezone
from .models import Configuration


class ApiClientMethod(Enum):
    GET = 'get'
    POST = 'post'
    DELETE = 'delete'


class BadgrApi:
    _config = None
    _api_host = 'https://api.badgr.io'
    _integration_name = 'EdxApiClient'

    def __init__(self, config=None):
        self._config = Configuration.get_config() if config is None else config

    def _update_access_token(self):
        url = '%s/o/token' % self._api_host

        headers = {
            'User-Agent': self._integration_name
        }

        r = requests.post(url, data={
            'grant_type': 'refresh_token',
            'refresh_token': self._config.get_refresh_token(),
        }, headers=headers)

        if not r.ok:
            username = self._config.get_account_login()
            password = self._config.get_account_password()

            if username and password:
                r = requests.post(url, data={
                    'username': username,
                    'password': password
                })
                if not r.ok:
                    msg = 'HTTP response [%s]: %s - %s' % (r.url, str(r.status_code), r.text)
                    raise Exception("Can't create new Badgr API token. %s" % msg)
            else:
                msg = 'HTTP response [%s]: %s - %s' % (r.url, str(r.status_code), r.text)
                raise Exception("Can't refresh Badgr API token. %s" % msg)

        resp_data = r.json()
        self._config.data['access_token'] = resp_data['access_token']
        self._config.data['refresh_token'] = resp_data['refresh_token']
        self._config.data['token_type'] = resp_data['token_type']
        expires_dt = timezone.now() + timedelta(seconds=resp_data['expires_in'])
        self._config.data['expires_dt'] = expires_dt.strftime(self._config.DATE_TEMPLATE)
        self._config.save()

    def _send_request(self, url_part, method=None, data=None, query_params=None, stop_on_error=False):
        access_token = self._config.get_access_token()
        token_type = self._config.get_token_type()

        if method is None:
            method = ApiClientMethod.GET

        if not access_token:
            self._update_access_token()

        url = url_part

        if query_params:
            url = url + '?' + '&'.join([k + '=' + str(v) for k, v in query_params.items()])
        url = self._api_host + url

        headers = {
            'Authorization': token_type + ' ' + access_token,
            'Content-Type': 'application/json',
            'User-Agent': self._integration_name
        }

        if method == ApiClientMethod.DELETE:
            r = requests.delete(url, json=data, headers=headers)
        elif method == ApiClientMethod.POST:
            r = requests.post(url, json=data, headers=headers)
        else:
            r = requests.get(url, headers=headers)

        if r.ok:
            return r.json()
        elif r.status_code in (401, 403) and not stop_on_error:
            self._update_access_token()
            return self._send_request(url_part, method, data=data, query_params=query_params, stop_on_error=True)
        else:
            err_msg = "Invalid API response from Badgr. Status code: %s. Response: %s" % (str(r.status_code), r.text)
            raise Exception(err_msg)

    def get_tokens(self):
        url_part = '/v2/auth/tokens'
        res = self._send_request(url_part)
        return res['result']

    def get_issuer(self, issuer_entity_id=None):
        issuer_entity_id = self._config.get_issuer_entity_id() if issuer_entity_id is None else issuer_entity_id
        url_part = '/v2/issuers/%s' % issuer_entity_id
        res = self._send_request(url_part)
        return res['result'][0] if isinstance(res['result'], list) else res['result']

    def get_badge_classes(self, issuer_entity_id=None):
        issuer_entity_id = self._config.get_issuer_entity_id() if issuer_entity_id is None else issuer_entity_id
        url_part = '/v2/issuers/%s/badgeclasses' % issuer_entity_id
        res = self._send_request(url_part)
        return res['result']

    def get_user_assertions(self, user_email):
        issuer_entity_id = self._config.get_issuer_entity_id()
        url_part = '/v2/issuers/%s/assertions' % issuer_entity_id
        query_params = {'recipient': user_email}
        res = self._send_request(url_part, query_params=query_params)
        return res['result']

    def create_user_assertion(self, user_email, badge_class_id, notify=True):
        url_part = '/v2/badgeclasses/%s/assertions' % badge_class_id
        data = {"recipient": {"identity": user_email, "type": "email"}, "notify": notify}
        res = self._send_request(url_part, method=ApiClientMethod.POST, data=data)
        return res['result'][0] if isinstance(res['result'], list) else res['result']

    def get_assertion(self, assertion_id):
        url_part = '/v2/assertions/%s' % assertion_id
        res = self._send_request(url_part)
        return res['result'][0] if isinstance(res['result'], list) else res['result']

    def remove_user_assertion(self, assertion_id):
        url_part = '/v2/assertions/%s' % assertion_id
        data = {"revocation_reason": "No reason"}
        res = self._send_request(url_part, method=ApiClientMethod.DELETE, data=data)
        return res['result']

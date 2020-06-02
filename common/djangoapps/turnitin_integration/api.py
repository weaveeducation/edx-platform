import datetime
import requests

from base64 import b64encode
from django.conf import settings
from django.core.urlresolvers import reverse
from .utils import log_action


class TurnitinApi(object):
    _host = ''
    _token = ''
    _key_id = None
    _allowed_file_formats = [
        'pdf', 'doc', 'ppt', 'pps', 'xls', 'docx', 'pptx', 'ppsx', 'xlsx',
        'xls', 'ps', 'rtf', 'htm', 'html', 'wpd', 'odt', 'txt'
    ]
    _integration_name = 'NimblywiseApiClient'
    _integration_version = '1.0.0'

    def __init__(self, api_key):
        main_host = "tii-sandbox.com" if api_key.use_sandbox else "turnitin.com"
        self._host = "https://%s.%s" % (api_key.url_part, main_host)
        self._token = api_key.key
        self._key_id = api_key.id

    def is_ext_supported(self, ext):
        return ext.lower() in self._allowed_file_formats

    def _send_request(self, api_part, method='get', data=None):
        url = self._host + '/api/v1' + api_part
        headers = {
            'Authorization': 'Bearer ' + self._token,
            'Content-Type': 'application/json',
            'X-Turnitin-Integration-Name': self._integration_name,
            'X-Turnitin-Integration-Version': self._integration_version
        }

        method = method.lower()

        if method == 'put':
            r = requests.put(url, json=data, headers=headers)
        elif method == 'post':
            r = requests.post(url, json=data, headers=headers)
        elif method == 'delete':
            r = requests.delete(url, headers=headers)
        else:
            r = requests.get(url, headers=headers)

        log_submitted = False

        try:
            content = r.json() if r.content else None
        except (ValueError, TypeError):
            log_action('turnitin_api', 'API error: ' + r.content, status_code=r.status_code)
            log_submitted = True
            content = None

        if not log_submitted and 400 <= r.status_code <= 500:
            log_action('turnitin_api', 'API error: ' + r.content, status_code=r.status_code)

        return r.status_code, content

    def get_eula_version(self):
        status_code, content = self._send_request('/eula/latest')
        if status_code == 200:
            return content['version'], content['url']
        return None, None

    def create_submission(self, turnitin_user, block_title, eula_version):
        owner = {
            "id": turnitin_user.user_id_hash,
            "email": turnitin_user.user.email
        }
        if turnitin_user.user.first_name:
            owner['given_name'] = turnitin_user.user.first_name
        if turnitin_user.user.last_name:
            owner['family_name'] = turnitin_user.user.last_name
        data = {
            "owner": turnitin_user.user_id_hash,
            "title": block_title,
            "eula": {
                "accepted_timestamp": datetime.datetime.now().replace(microsecond=0).isoformat() + 'Z',
                "language": "en-US",
                "version": eula_version
            },
            "metadata": {
                "owners": [owner]
            }
        }
        status_code, content = self._send_request('/submissions', method='post', data=data)
        if status_code == 201:
            return status_code, content
        return status_code, None

    def upload_file(self, submission_id, file_name, file_content):
        url = self._host + '/api/v1/submissions/%s/original' % submission_id
        headers = {
            'Authorization': 'Bearer ' + self._token,
            'Content-Disposition': 'inline; filename="' + file_name + '"',
            'X-Turnitin-Integration-Name': self._integration_name,
            'X-Turnitin-Integration-Version': self._integration_version
        }

        r = requests.put(url, data=file_content, headers=headers)
        if r.status_code == 202:
            return r.status_code, True
        return r.status_code, False

    def create_report(self, submission_id):
        data = {
            "generation_settings": {
                "search_repositories": [
                    "INTERNET",
                    "SUBMITTED_WORK",
                    "PUBLICATION",
                    "CROSSREF",
                    "CROSSREF_POSTED_CONTENT"
                ]
            }
        }
        status_code, content = self._send_request('/submissions/' + submission_id + '/similarity',
                                                  method='put', data=data)
        if status_code == 202:
            return status_code, True
        return status_code, False

    def create_viewer_launch_url(self, submission_id, turnitin_user):
        data = {
            "viewer_user_id": turnitin_user.user_id_hash,
            "locale": "en"
        }
        status_code, content = self._send_request('/submissions/' + submission_id + '/viewer-url',
                                                  method='post', data=data)
        if status_code == 200:
            return status_code, content['viewer_url']
        return status_code, None

    def create_webhook(self):
        webhook_host = settings.TURNITIN_WEBHOOK_HOST + reverse('turnitin_callback')
        data = {
            "allow_insecure": True,
            "signing_secret": b64encode(settings.TURNITIN_SIGNING_SECRET),
            "description": "Webhook " + str(self._key_id),
            "url": webhook_host,
            "event_types": [
                "SUBMISSION_COMPLETE",
                "SIMILARITY_COMPLETE",
                "SIMILARITY_UPDATED"
            ]
        }
        status_code, content = self._send_request('/webhooks', method='post', data=data)
        if status_code == 201:
            return status_code, content['id'], webhook_host
        return status_code, None, webhook_host

    def remove_webhook(self, webhook_id):
        status_code, content = self._send_request('/webhooks/' + webhook_id, method='delete')
        if status_code == 204:
            return status_code, True
        return status_code, False

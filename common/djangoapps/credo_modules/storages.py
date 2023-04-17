from django.core.files.storage import FileSystemStorage
from django.utils.encoding import filepath_to_uri
from urllib.parse import urlparse, urlencode, urlunparse, parse_qs
from storages.backends.s3boto import S3BotoStorage


class PublicS3BotoStorage(S3BotoStorage):

    def url(self, name, **kwargs):
        url_orig = super().url(name, **kwargs)
        scheme, netloc, path, params, query, fragment = urlparse(url_orig)
        query_params = parse_qs(query)
        if 'x-amz-security-token' in query_params:
            del query_params['x-amz-security-token']
        query = urlencode(query_params)
        return urlunparse((scheme, netloc, path, params, query, fragment))


class ScormLocalFileSystemStorage(FileSystemStorage):

    def url(self, *args, **kwargs):
        from django.conf import settings
        from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
        url_schema = "https://"
        if settings.DEBUG:
            url_schema = "http://"

        if settings.ROOT_URLCONF == 'cms.urls':
            base_url = configuration_helpers.get_value('CMS_BASE', "")
            root_url = f"{url_schema}{base_url}"
        else:
            root_url = configuration_helpers.get_value('LMS_ROOT_URL', "")
        url_orig = super().url(*args, **kwargs)
        return f"{root_url}{url_orig}"


class ScormS3Storage(S3BotoStorage):

    def url(self, name, headers=None, response_headers=None, expire=None):
        from django.conf import settings
        from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
        url_schema = "https://"
        if settings.DEBUG:
            url_schema = "http://"

        name = self._normalize_name(self._clean_name(name))
        if settings.ROOT_URLCONF == 'cms.urls':
            base_url = configuration_helpers.get_value('CMS_BASE', "")
            root_url = f"{url_schema}{base_url}"
        else:
            root_url = configuration_helpers.get_value('LMS_ROOT_URL', "")

        return '%s/%s' % (root_url, filepath_to_uri(name))

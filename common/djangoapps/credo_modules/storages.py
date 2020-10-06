from urllib.parse import urlparse, urlencode, urlunparse, parse_qs
from storages.backends.s3boto import S3BotoStorage


class PublicS3BotoStorage(S3BotoStorage):

    def url(self, name, **kwargs):
        url_orig = super(PublicS3BotoStorage, self).url(name, **kwargs)
        scheme, netloc, path, params, query, fragment = urlparse(url_orig)
        query_params = parse_qs(query)
        if 'x-amz-security-token' in query_params:
            del query_params['x-amz-security-token']
        query = urlencode(query_params)
        return urlunparse((scheme, netloc, path, params, query, fragment))

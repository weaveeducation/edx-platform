from django.core.cache.backends.memcached import MemcachedCache
try:
    import cPickle as pickle
except ImportError:
    import pickle


class CredoMemcachedCache(MemcachedCache):

    @property
    def _cache(self):
        if getattr(self, '_client', None) is None:
            self._client = self._lib.Client(self._servers, pickleProtocol=pickle.HIGHEST_PROTOCOL,
                                            server_max_value_length=5242880)
        return self._client

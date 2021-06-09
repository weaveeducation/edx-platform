import time
from .models import Profiler


class Profiling:
    _data = None
    _req_name = None
    _is_active = True

    def __init__(self):
        self._data = {}
        self._req_name = 'unknown'

    def activate(self):
        self._is_active = True

    def deactivate(self):
        self._is_active = False

    def set_request_name(self, req_name):
        self._req_name = req_name

    def start_event(self, event):
        self._data[event] = time.time()

    def finish_event(self, event):
        if self._is_active and event in self._data:
            time_diff = str(time.time() - self._data.get(event))
            p_obj = Profiler(
                request_name=self._req_name,
                event=event,
                time=time_diff
            )
            p_obj.save()

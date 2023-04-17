from lms import CELERY_APP
from .service import badges_sync


@CELERY_APP.task
def badges_sync_task():
    badges_sync()

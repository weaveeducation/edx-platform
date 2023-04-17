"""Get log settings."""


import logging
import platform
import sys
import warnings
import json
import socket
from logging.handlers import SysLogHandler, SYSLOG_UDP_PORT
from logging import Handler
from django.db import transaction

LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']


class DBHandler(Handler):

    model = None
    allowed_events = [
        'problem_check',
        'edx.drag_and_drop_v2.item.dropped',
        'openassessmentblock.create_submission',
        'openassessmentblock.staff_assess',
        'openassessmentblock.self_assess',
        'openassessmentblock.peer_assess',
        'sequential_block.viewed',
        'xblock.image-explorer.hotspot.opened',
        'xblock.text-highlighter.new_submission',
        'xblock.freetextresponse.submit'
    ]

    def emit(self, record):
        if not self.model:
            from common.djangoapps.credo_modules.models import DBLogEntry
            self.model = DBLogEntry
        msg = record.getMessage()
        try:
            data = json.loads(msg)
        except ValueError:
            return
        event_type = data.get('event_type')
        event_source = data.get('event_source')

        if event_type not in self.allowed_events or event_source != 'server':
            return

        user_id = data.get('context', {}).get('user_id', None)
        course_id = data.get('context', {}).get('course_id', None)
        if event_type == 'sequential_block.viewed':
            block_id = data.get('event', {}).get('usage_key', None)
        else:
            block_id = data.get('context', {}).get('module', {}).get('usage_key', None)

        if event_type == 'xblock.image-explorer.hotspot.opened':
            new_grade = data.get('event', {}).get('new_grade')
            if not new_grade:
                return

        if user_id and course_id and block_id:
            with transaction.atomic():
                formatted_msg = msg.replace('||', ';')
                item = self.model(
                    event_name=event_type,
                    user_id=user_id,
                    course_id=course_id,
                    block_id=block_id,
                    message=formatted_msg
                )
                item.save()


def get_logger_config(log_dir,  # lint-amnesty, pylint: disable=unused-argument
                      logging_env="no_env",
                      local_loglevel='INFO',
                      service_variant="",
                      syslog_settings=None):
    """

    Return the appropriate logging config dictionary. You should assign the
    result of this to the LOGGING var in your settings. The reason it's done
    this way instead of registering directly is because I didn't want to worry
    about resetting the logging state if this is called multiple times when
    settings are extended.
    """

    # Revert to INFO if an invalid string is passed in
    if local_loglevel not in LOG_LEVELS:
        local_loglevel = 'INFO'

    if syslog_settings is None:
        syslog_settings = {
            'SYSLOG_USE_TCP': False,
            'SYSLOG_HOST': '',
            'SYSLOG_PORT': 0
        }

    hostname = platform.node().split(".")[0]
    syslog_format = ("[service_variant={service_variant}]"
                     "[%(name)s][env:{logging_env}] %(levelname)s "
                     "[{hostname}  %(process)d] [user %(userid)s] [ip %(remoteip)s] [%(filename)s:%(lineno)d] "
                     "- %(message)s").format(service_variant=service_variant,
                                             logging_env=logging_env,
                                             hostname=hostname)

    syslog_use_tcp = syslog_settings.get('SYSLOG_USE_TCP', False)
    syslog_host = syslog_settings.get('SYSLOG_HOST', '')
    syslog_port = syslog_settings.get('SYSLOG_PORT', SYSLOG_UDP_PORT)

    logger_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s %(levelname)s %(process)d '
                          '[%(name)s] [user %(userid)s] [ip %(remoteip)s] %(filename)s:%(lineno)d - %(message)s',
            },
            'syslog_format': {'format': syslog_format},
            'raw': {'format': '%(message)s'},
        },
        'filters': {
            'require_debug_false': {
                '()': 'django.utils.log.RequireDebugFalse',
            },
            'userid_context': {
                '()': 'edx_django_utils.logging.UserIdFilter',
            },
            'remoteip_context': {
                '()': 'edx_django_utils.logging.RemoteIpFilter',
            }
        },
        'handlers': {
            'console': {
                'level': 'INFO',
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'filters': ['userid_context', 'remoteip_context'],
                'stream': sys.stderr,
            },
            'mail_admins': {
                'level': 'ERROR',
                'filters': ['require_debug_false'],
                'class': 'django.utils.log.AdminEmailHandler'
            },
            'local': {
                'level': local_loglevel,
                'class': 'logging.handlers.SysLogHandler',
                'address': (syslog_host, syslog_port) if syslog_host else '/dev/log',
                'socktype': socket.SOCK_STREAM if syslog_use_tcp else socket.SOCK_DGRAM,
                'formatter': 'syslog_format',
                'filters': ['userid_context', 'remoteip_context'],
                'facility': SysLogHandler.LOG_LOCAL0,
            },
            'tracking': {
                'level': 'DEBUG',
                'class': 'logging.handlers.SysLogHandler',
                'address': (syslog_host, syslog_port) if syslog_host else '/dev/log',
                'socktype': socket.SOCK_STREAM if syslog_use_tcp else socket.SOCK_DGRAM,
                'facility': SysLogHandler.LOG_LOCAL1,
                'formatter': 'raw',
            },
            'log_db': {
                'level': 'INFO',
                'class': 'openedx.core.lib.logsettings.DBHandler',
                'formatter': 'raw',
            },
            'credo_json': {
                'level': 'DEBUG',
                'class': 'logging.handlers.SysLogHandler',
                'address': (syslog_host, syslog_port) if syslog_host else '/dev/log',
                'socktype': socket.SOCK_STREAM if syslog_use_tcp else socket.SOCK_DGRAM,
                'facility': SysLogHandler.LOG_LOCAL2,
                'formatter': 'syslog_format',
            },
        },
        'loggers': {
            'credo_json': {
                'handlers': ['console', 'credo_json'],
                'level': 'DEBUG',
                'propagate': False,
            },
            'tracking': {
                'handlers': ['tracking', 'log_db'],
                'level': 'DEBUG',
                'propagate': False,
            },
            '': {
                'handlers': ['console', 'local'],
                'level': 'INFO',
                'propagate': False
            },
            'django.request': {
                'handlers': ['mail_admins'],
                'level': 'ERROR',
                'propagate': True,
            },
            # requests is so loud at INFO (logs every connection) that we
            # force it to warn by default.
            'requests.packages.urllib3': {
                'level': 'WARN'
            }
        }
    }

    return logger_config


def suppress_warning_exception(fn):
    def warn(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        except Exception as e:
            logging.warning(str(e))
    return warn


def log_python_warnings():
    """
    Stop ignoring DeprecationWarning, ImportWarning, and PendingDeprecationWarning;
    log all Python warnings to the main log file.

    Not used in test runs, so pytest can collect the warnings triggered for
    each test case.
    """
    warnings.simplefilter('default')
    warnings.filterwarnings('ignore', 'Not importing directory ')
    warnings.filterwarnings('ignore', 'Setting _field_data is deprecated')
    warnings.filterwarnings('ignore', 'Setting _field_data via the constructor is deprecated')
    warnings.filterwarnings('ignore', '.*unclosed.*', category=ResourceWarning)
    try:
        # There are far too many of these deprecation warnings in startup to output for every management command;
        # suppress them until we've fixed at least the most common ones as reported by the test suite
        from django.utils.deprecation import RemovedInDjango40Warning, RemovedInDjango41Warning
        warnings.simplefilter('ignore', RemovedInDjango40Warning)
        warnings.simplefilter('ignore', RemovedInDjango41Warning)
    except ImportError:
        pass
    logging.captureWarnings(True)


def get_docker_logger_config(log_dir='/var/tmp',
                             logging_env="no_env",
                             edx_filename="edx.log",
                             dev_env=False,
                             debug=False,
                             service_variant='lms'):
    """
    Return the appropriate logging config dictionary for a docker based setup.
    You should assign the result of this to the LOGGING var in your settings.
    """

    hostname = platform.node().split(".")[0]
    syslog_format = (
        "[service_variant={service_variant}]"
        "[%(name)s][env:{logging_env}] %(levelname)s "
        "[{hostname}  %(process)d] [%(filename)s:%(lineno)d] "
        "- %(message)s"
    ).format(
        service_variant=service_variant,
        logging_env=logging_env, hostname=hostname
    )

    handlers = ['console']

    logger_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s %(levelname)s %(process)d '
                          '[%(name)s] %(filename)s:%(lineno)d - %(message)s',
            },
            'syslog_format': {'format': syslog_format},
            'raw': {'format': '%(message)s'},
        },
        'filters': {
            'require_debug_false': {
                '()': 'django.utils.log.RequireDebugFalse',
            },
            'userid_context': {
                '()': 'edx_django_utils.logging.UserIdFilter',
            },
            'remoteip_context': {
                '()': 'edx_django_utils.logging.RemoteIpFilter',
            }
        },
        'handlers': {
            'console': {
                'level': 'DEBUG' if debug else 'INFO',
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'filters': ['userid_context', 'remoteip_context'],
                'stream': sys.stderr,
            },
            'tracking': {
                'level': 'DEBUG',
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': '/var/tmp/tracking_logs.log',
                'backupCount': 5,
                'formatter': 'raw',
                'maxBytes': 10485760
            }
        },
        'loggers': {
            'django': {
                'handlers': handlers,
                'propagate': True,
                'level': 'INFO'
            },
            'tracking': {
                'handlers': ['tracking'],
                'level': 'DEBUG',
                'propagate': False,
            },
            'requests': {
                'handlers': handlers,
                'propagate': True,
                'level': 'WARNING'
            },
            'factory': {
                'handlers': handlers,
                'propagate': True,
                'level': 'WARNING'
            },
            'django.request': {
                'handlers': handlers,
                'propagate': True,
                'level': 'ERROR'
            },
            '': {
                'handlers': handlers,
                'level': 'INFO',
                'propagate': False
            },
        }
    }

    return logger_config

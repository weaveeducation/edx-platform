"""Get log settings."""

import logging
import json
import platform
import socket
import sys
import warnings
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
        'edx.grades.problem.submitted'
    ]

    def emit(self, record):
        if not self.model:
            from credo_modules.models import DBLogEntry
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

        if event_type == 'edx.grades.problem.submitted':
            if '@image-explorer+block@' in block_id:
                event_type = "xblock.image-explorer.hotspot.opened"
                data['name'] = event_type
                data['event_type'] = event_type
                data['event']['event_transaction_type'] = event_type
                msg = json.dumps(data)
            else:
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


class ExtendedSysLogHandler(SysLogHandler):

    def emit(self, record):
        """
        Emit a record.

        The record is formatted, and then sent to the syslog server. If
        exception information is present, it is NOT sent to the server.
        """
        try:
            msg = self.format(record)
            """
            We need to convert record level to lowercase, maybe this will
            change in the future.
            """
            prio = '<%d>' % self.encodePriority(self.facility,
                                                self.mapPriority(record.levelname))
            # Message is a string. Convert to bytes as required by RFC 5424
            if type(msg) is unicode:
                msg = msg.encode('utf-8')
            msg = prio + msg
            if self.unixsocket:
                try:
                    self.socket.send(msg)
                except socket.error:
                    self.socket.close() # See issue 17981
                    self._connect_unixsocket(self.address)
                    self.socket.send(msg)
            elif self.socktype == socket.SOCK_DGRAM:
                self.socket.sendto(msg, self.address)
            else:
                self.socket.sendall(msg)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


def get_logger_config(log_dir,
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
                     "[{hostname}  %(process)d] [%(filename)s:%(lineno)d] "
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
                          '[%(name)s] %(filename)s:%(lineno)d - %(message)s',
            },
            'syslog_format': {'format': syslog_format},
            'raw': {'format': '%(message)s'},
        },
        'filters': {
            'require_debug_false': {
                '()': 'django.utils.log.RequireDebugFalse',
            }
        },
        'handlers': {
            'console': {
                'level': 'INFO',
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'stream': sys.stderr,
            },
            'mail_admins': {
                'level': 'ERROR',
                'filters': ['require_debug_false'],
                'class': 'django.utils.log.AdminEmailHandler'
            },
            'local': {
                'level': local_loglevel,
                'class': 'openedx.core.lib.logsettings.ExtendedSysLogHandler',
                'address': (syslog_host, syslog_port) if syslog_host else '/dev/log',
                'socktype': socket.SOCK_STREAM if syslog_use_tcp else socket.SOCK_DGRAM,
                'formatter': 'syslog_format',
                'facility': SysLogHandler.LOG_LOCAL0,
            },
            'tracking': {
                'level': 'DEBUG',
                'class': 'openedx.core.lib.logsettings.ExtendedSysLogHandler',
                'address': (syslog_host, syslog_port) if syslog_host else '/dev/log',
                'socktype': socket.SOCK_STREAM if syslog_use_tcp else socket.SOCK_DGRAM,
                'facility': SysLogHandler.LOG_LOCAL1,
                'formatter': 'syslog_format',
            },
            'log_db': {
                'level': 'INFO',
                'class': 'openedx.core.lib.logsettings.DBHandler',
                'formatter': 'raw',
            }
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

    if logging_env in ['sandbox', 'dev']:
        logger_config['handlers'].update({
            'credo_json': {
                'level': 'DEBUG',
                'class': 'logging.NullHandler',
            },
        })
    else:
        logger_config['handlers'].update({
            'credo_json': {
                'level': 'DEBUG',
                'class': 'openedx.core.lib.logsettings.ExtendedSysLogHandler',
                'address': (syslog_host, syslog_port) if syslog_host else '/dev/log',
                'socktype': socket.SOCK_STREAM if syslog_use_tcp else socket.SOCK_DGRAM,
                'facility': SysLogHandler.LOG_LOCAL2,
                'formatter': 'syslog_format',
            },
        })

    return logger_config


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
    try:
        # There are far too many of these deprecation warnings in startup to output for every management command;
        # suppress them until we've fixed at least the most common ones as reported by the test suite
        from django.utils.deprecation import RemovedInDjango20Warning, RemovedInDjango21Warning
        warnings.simplefilter('ignore', RemovedInDjango20Warning)
        warnings.simplefilter('ignore', RemovedInDjango21Warning)
    except ImportError:
        pass
    logging.captureWarnings(True)

"""
Helper functions for managing interactions with the LTI outcomes service defined
in LTI v1.1.
"""

import logging
import hashlib
import time
import uuid

import requests
import requests_oauthlib
from lxml import etree
from lxml.builder import ElementMaker
from requests.exceptions import RequestException

from lms.djangoapps.lti_provider.models import GradedAssignment, OutcomeService

log = logging.getLogger("edx.lti_provider")


class OutcomeServiceSendScoreError(Exception):
    def __init__(self, message, response_body=None, request_body=None,
                 lis_outcome_service_url=None, request_error=None):
        super().__init__(message)
        self.response_body = response_body
        self.request_body = request_body
        self.lis_outcome_service_url = lis_outcome_service_url
        self.request_error = request_error


def store_outcome_parameters(request_params, user, lti_consumer):
    """
    Determine whether a set of LTI launch parameters contains information about
    an expected score, and if so create a GradedAssignment record. Create a new
    OutcomeService record if none exists for the tool consumer, and update any
    incomplete record with additional data if it is available.
    """
    result_id = request_params.get('lis_result_sourcedid', None)

    # We're only interested in requests that include a lis_result_sourcedid
    # parameter. An LTI consumer that does not send that parameter does not
    # expect scoring updates for that particular request.
    if result_id:
        result_service = request_params.get('lis_outcome_service_url', None)
        if not result_service:
            # TODO: There may be a way to recover from this error; if we know
            # the LTI consumer that the request comes from then we may be able
            # to figure out the result service URL. As it stands, though, this
            # is a badly-formed LTI request
            log.warning(
                "Outcome Service: lis_outcome_service_url parameter missing "
                "from scored assignment; we will be unable to return a score. "
                "Request parameters: %s",
                request_params
            )
            return

        # Both usage and course ID parameters are supplied in the LTI launch URL
        usage_key = request_params['usage_key']
        course_key = request_params['course_key']

        # Create a record of the outcome service if necessary
        outcomes, __ = OutcomeService.objects.get_or_create(
            lis_outcome_service_url=result_service,
            lti_consumer=lti_consumer
        )

        result_id_hash = hashlib.md5(str(result_id).encode('utf-8')).hexdigest()
        try:
            assignment = GradedAssignment.objects.get(
                lis_result_sourcedid=result_id_hash,
                outcome_service=outcomes,
                course_key=course_key,
                usage_key=usage_key,
                user=user
            )
        except GradedAssignment.DoesNotExist:
            try:
                other_assignment = GradedAssignment.objects.get(
                    lis_result_sourcedid=result_id_hash,
                    outcome_service=outcomes,
                )
                postfix = '_' + str(int(time.time())) + '_disabled'
                other_assignment.lis_result_sourcedid = other_assignment.lis_result_sourcedid + postfix
                other_assignment.disabled = True
                other_assignment.save()
            except GradedAssignment.DoesNotExist:
                pass
            assignment = GradedAssignment(
                lis_result_sourcedid=result_id_hash,
                course_key=course_key,
                usage_key=usage_key,
                user=user,
                outcome_service=outcomes,
                lis_result_sourcedid_value=result_id
            )
            assignment.save()
        return assignment, outcomes
    return None, None


def generate_replace_result_xml(result_sourcedid, score):
    """
    Create the XML document that contains the new score to be sent to the LTI
    consumer. The format of this message is defined in the LTI 1.1 spec.
    """
    # Pylint doesn't recognize members in the LXML module
    elem = ElementMaker(nsmap={None: 'http://www.imsglobal.org/services/ltiv1p1/xsd/imsoms_v1p0'})
    xml = elem.imsx_POXEnvelopeRequest(
        elem.imsx_POXHeader(
            elem.imsx_POXRequestHeaderInfo(
                elem.imsx_version('V1.0'),
                elem.imsx_messageIdentifier(str(uuid.uuid4()))
            )
        ),
        elem.imsx_POXBody(
            elem.replaceResultRequest(
                elem.resultRecord(
                    elem.sourcedGUID(
                        elem.sourcedId(result_sourcedid)
                    ),
                    elem.result(
                        elem.resultScore(
                            elem.language('en'),
                            elem.textString(str(score))
                        )
                    )
                )
            )
        )
    )
    return etree.tostring(xml, xml_declaration=True, encoding='UTF-8')


def get_assignments_for_problem(problem_descriptor, user_id, course_key):
    """
    Trace the parent hierarchy from a given problem to find all blocks that
    correspond to graded assignment launches for this user. A problem may
    show up multiple times for a given user; the problem could be embedded in
    multiple courses (or multiple times in the same course), or the block could
    be embedded more than once at different granularities (as an individual
    problem and as a problem in a vertical, for example).

    Returns a list of GradedAssignment objects that are associated with the
    given descriptor for the current user.
    """
    locations = []
    current_descriptor = problem_descriptor
    while current_descriptor:
        if current_descriptor.graded:
            locations.append(current_descriptor.location)
        if current_descriptor.category == 'sequential':
            break
        current_descriptor = current_descriptor.get_parent()
    if not locations:
        return []
    assignments = GradedAssignment.objects.filter(
        user=user_id, course_key=course_key, usage_key__in=locations, disabled=False
    )
    return assignments


def send_score_update(assignment, score, attempt_num=0, countdown=0):
    """
    Create and send the XML message to the campus LMS system to update the grade
    for a single graded assignment.
    """
    xml = generate_replace_result_xml(
        assignment.lis_result_sourcedid_value, score
    )
    request_error = None
    try:
        response = sign_and_send_replace_result(assignment, xml)
    except RequestException as exc:
        # failed to send result. 'response' is None, so more detail will be
        # logged at the end of the method.
        response = None
        request_error = str(exc)
        log.exception("Outcome Service: Error when sending result.")

    # If something went wrong, make sure that we have a complete log record.
    # That way we can manually fix things up on the campus system later if
    # necessary.
    if not (response and check_replace_result_response(response)):
        response_body = response.text if response else 'Unknown'
        log.debug('Outcome service url: %s', assignment.outcome_service.lis_outcome_service_url)
        log.debug('Request body: %s', xml)
        log.debug('Response body: %s', response_body)
        error_msg = "Outcome Service: Failed to update score on LTI consumer. " \
                    "User: %s, course: %s, usage: %s, score: %s, url: %s, status: %s, attempt num: %s" %\
                    (assignment.user, assignment.course_key, assignment.usage_key, score,
                     assignment.outcome_service.lis_outcome_service_url, response, str(attempt_num))

        if attempt_num in [4, 7]:
            if attempt_num == 4:
                error_msg = error_msg + '. Will be retried in ' + str(countdown) + 's'
            else:
                error_msg = error_msg + '. Final attempt'
            log.error(error_msg, exc_info=True)
        raise OutcomeServiceSendScoreError(error_msg, response_body, xml,
                                           assignment.outcome_service.lis_outcome_service_url, request_error)

    return {
        'request_body': xml,
        'response_body': response.text if response else 'Unknown',
        'lis_outcome_service_url': assignment.outcome_service.lis_outcome_service_url
    }


def sign_and_send_replace_result(assignment, xml):
    """
    Take the XML document generated in generate_replace_result_xml, and sign it
    with the consumer key and secret assigned to the consumer. Send the signed
    message to the LTI consumer.
    """
    outcome_service = assignment.outcome_service
    consumer = outcome_service.lti_consumer
    consumer_key = consumer.consumer_key
    consumer_secret = consumer.consumer_secret

    # Calculate the OAuth signature for the replace_result message.
    oauth = requests_oauthlib.OAuth1(
        consumer_key,
        consumer_secret,
        signature_method='HMAC-SHA1',
        force_include_body=True,
        decoding=None
    )

    headers = {'content-type': 'application/xml'}
    response = requests.post(
        assignment.outcome_service.lis_outcome_service_url,
        data=xml,
        auth=oauth,
        headers=headers
    )

    return response


def check_replace_result_response(response):
    """
    Parse the response sent by the LTI consumer after an score update message
    has been processed. Return True if the message was properly received, or
    False if not. The format of this message is defined in the LTI 1.1 spec.
    """
    # Pylint doesn't recognize members in the LXML module
    if response.status_code != 200:
        log.error(
            "Outcome service response: Unexpected status code %s",
            response.status_code,
            exc_info=True
        )
        return False

    try:
        xml = response.content
        root = etree.fromstring(xml)
    except etree.ParseError as ex:
        log.error("Outcome service response: Failed to parse XML: %s\n %s", ex, xml, exc_info=True)
        return False

#    major_codes = root.xpath(
#        '//ns:imsx_codeMajor',
#        namespaces={'ns': 'http://www.imsglobal.org/services/ltiv1p1/xsd/imsoms_v1p0'})
    major_codes = root.xpath("//*[local-name() = 'imsx_codeMajor']")
    if len(major_codes) != 1:
        log.error(
            "Outcome service response: Expected exactly one imsx_codeMajor field in response. Received %s",
            major_codes,
            exc_info=True
        )
        return False

    if major_codes[0].text != 'success':
        log.error(
            "Outcome service response: Unexpected major code: %s.",
            major_codes[0].text,
            exc_info=True
        )
        return False

    return True

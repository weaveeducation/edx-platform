"""
Code to manage fetching and storing the metadata of IdPs.
"""


import logging

import requests
from celery import shared_task
from edx_django_utils.monitoring import set_code_owner_attribute
from lxml import etree
from requests import exceptions

from common.djangoapps.third_party_auth.models import SAMLConfiguration, SAMLProviderConfig
from common.djangoapps.third_party_auth.utils import (
    MetadataParseError,
    create_or_update_saml_provider_data,
    parse_metadata_xml,
)

log = logging.getLogger(__name__)

SAML_XML_NS = 'urn:oasis:names:tc:SAML:2.0:metadata'  # The SAML Metadata XML namespace


@shared_task
@set_code_owner_attribute
def fetch_saml_metadata():
    """
    Fetch and store/update the metadata of all IdPs

    This task should be run on a daily basis.
    It's OK to run this whether or not SAML is enabled.

    Return value:
        tuple(num_skipped, num_attempted, num_updated, num_failed, failure_messages)
        num_total: Total number of providers found in the database
        num_skipped: Number of providers skipped for various reasons (see L52)
        num_attempted: Number of providers whose metadata was fetched
        num_updated: Number of providers that are either new or whose metadata has changed
        num_failed: Number of providers that could not be updated
        failure_messages: List of error messages for the providers that could not be updated
    """

    # First make a list of all the metadata XML URLs:
    saml_providers = SAMLProviderConfig.key_values('slug', flat=True)
    num_total = len(saml_providers)
    num_skipped = 0
    url_map = {}
    for idp_slug in saml_providers:
        config = SAMLProviderConfig.current(idp_slug)
        saml_config_slug = config.saml_configuration.slug if config.saml_configuration else 'default'

        # Skip SAML provider configurations which do not qualify for fetching
        if any([
            not config.enabled,
            not config.automatic_refresh_enabled,
            not SAMLConfiguration.is_enabled(config.site, saml_config_slug)
        ]):
            num_skipped += 1
            continue

        url = config.metadata_source
        if url not in url_map:
            url_map[url] = []
        if config.entity_id not in url_map[url]:
            url_map[url].append(config.entity_id)

    # Now attempt to fetch the metadata for the remaining SAML providers:
    num_attempted = len(url_map)
    num_updated = 0
    failure_messages = []  # We return the length of this array for num_failed
    for url, entity_ids in url_map.items():
        try:
            log.info("Fetching %s", url)
            if not url.lower().startswith('https'):
                log.warning("This SAML metadata URL is not secure! It should use HTTPS. (%s)", url)
            response = requests.get(url, verify=True, headers={'User-Agent': 'nw-http-client'})  # May raise HTTPError or SSLError or ConnectionError
            response.raise_for_status()  # May raise an HTTPError

            try:
                parser = etree.XMLParser(remove_comments=True)
                xml = etree.fromstring(response.content, parser)
            except etree.XMLSyntaxError:  # lint-amnesty, pylint: disable=try-except-raise
                raise
            # TODO: Can use OneLogin_Saml2_Utils to validate signed XML if anyone is using that

            for entity_id in entity_ids:
                log.info("Processing IdP with entityID %s", entity_id)
                public_key, sso_url, expires_at = parse_metadata_xml(xml, entity_id)
                changed = create_or_update_saml_provider_data(entity_id, public_key, sso_url, expires_at)
                if changed:
                    log.info(f"→ Created new record for SAMLProviderData for entityID {entity_id}")
                    num_updated += 1
                else:
                    log.info(f"→ Updated existing SAMLProviderData. Nothing has changed for entityID {entity_id}")
        except (exceptions.SSLError, exceptions.HTTPError, exceptions.RequestException, MetadataParseError) as error:
            # Catch and process exception in case of errors during fetching and processing saml metadata.
            # Here is a description of each exception.
            # SSLError is raised in case of errors caused by SSL (e.g. SSL cer verification failure etc.)
            # HTTPError is raised in case of unexpected status code (e.g. 500 error etc.)
            # RequestException is the base exception for any request related error that "requests" lib raises.
            # MetadataParseError is raised if there is error in the fetched meta data (e.g. missing @entityID etc.)

            log.exception(str(error))
            failure_messages.append(
                "{error_type}: {error_message}\nMetadata Source: {url}\nEntity IDs: \n{entity_ids}.".format(
                    error_type=type(error).__name__,
                    error_message=str(error),
                    url=url,
                    entity_ids="\n".join(
                        [f"\t{count}: {item}" for count, item in enumerate(entity_ids, start=1)],
                    )
                )
            )
        except etree.XMLSyntaxError as error:
            log.exception(str(error))
            failure_messages.append(
                "XMLSyntaxError: {error_message}\nMetadata Source: {url}\nEntity IDs: \n{entity_ids}.".format(
                    error_message=str(error.error_log),  # lint-amnesty, pylint: disable=no-member
                    url=url,
                    entity_ids="\n".join(
                        [f"\t{count}: {item}" for count, item in enumerate(entity_ids, start=1)],
                    )
                )
            )

    # Return counts for total, skipped, attempted, updated, and failed, along with any failure messages
    return num_total, num_skipped, num_attempted, num_updated, len(failure_messages), failure_messages

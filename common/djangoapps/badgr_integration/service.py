from django.db import transaction
from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from lms.djangoapps.courseware.completion_check import check_sequential_block_is_completed
from openedx.core.djangoapps.content.block_structure.models import BlockCache
from opaque_keys.edx.keys import UsageKey
from xmodule.modulestore.django import modulestore
from .models import Assertion, Badge, Configuration, Issuer
from .api_client import BadgrApi
from .utils import org_badgr_enabled


def badges_sync():
    config = Configuration.get_config()
    issuer_entity_id = config.get_issuer_entity_id()

    api_client = BadgrApi(config=config)

    created, updated, deactivated = 0, 0, 0

    issuer_api_res = api_client.get_issuer(issuer_entity_id)

    issuer_obj = Issuer.objects.filter(external_id=issuer_entity_id).first()
    if issuer_obj:
        if not issuer_obj.is_active \
          or issuer_obj.title != issuer_api_res['name'] \
          or issuer_obj.description != issuer_api_res['description'] \
          or issuer_obj.url != issuer_api_res['openBadgeId'] \
          or issuer_obj.image_url != issuer_api_res['image']:

            issuer_obj.is_active = True
            issuer_obj.title = issuer_api_res['name']
            issuer_obj.url = issuer_api_res['openBadgeId']
            issuer_obj.description = issuer_api_res['description']
            issuer_obj.image_url = issuer_api_res['image']
            issuer_obj.save()
    else:
        issuer_obj = Issuer(
            title=issuer_api_res['name'],
            external_id=issuer_api_res['entityId'],
            is_active=True,
            description=issuer_api_res['description'],
            url=issuer_api_res['openBadgeId'],
            image_url=issuer_api_res['image']
        )
        issuer_obj.save()

    badges = Badge.objects.filter(issuer=issuer_obj)
    badges_dict = {b.external_id: b for b in badges}
    existing_badges = []

    badge_classes = api_client.get_badge_classes(issuer_entity_id)
    for b_cl in badge_classes:
        existing_badges.append(b_cl['entityId'])

        #r = requests.head(b_cl['image'], allow_redirects=True)
        #image_url = r.url
        image_url = b_cl['image']

        if b_cl['entityId'] in badges_dict:
            badge_obj = badges_dict[b_cl['entityId']]
            if not badge_obj.is_active \
              or badge_obj.title != b_cl['name'] \
              or badge_obj.description != b_cl['description'] \
              or badge_obj.criteria_narrative != b_cl['criteriaNarrative'] \
              or badge_obj.url != b_cl['openBadgeId'] \
              or badge_obj.image_url != image_url:
                print('Update badge: ' + str(badge_obj))

                badge_obj.is_active = True
                badge_obj.title = b_cl['name']
                badge_obj.url = b_cl['openBadgeId']
                badge_obj.description = b_cl['description']
                badge_obj.criteria_narrative = b_cl['criteriaNarrative']
                badge_obj.image_url = image_url
                badge_obj.save()
                updated += 1
        else:
            print('Create new badge: ' + b_cl['name'])
            badge_obj = Badge(
                title=b_cl['name'],
                external_id=b_cl['entityId'],
                is_active=True,
                issuer=issuer_obj,
                description=b_cl['description'],
                criteria_narrative=b_cl['criteriaNarrative'],
                url=b_cl['openBadgeId'],
                image_url=image_url,
            )
            badge_obj.save()
            created += 1

    for b in badges:
        if b.external_id not in existing_badges:
            print('Deactivate badge: ' + str(b))
            b.is_active = False
            b.save()
            deactivated += 1

    return created, updated, deactivated


class BadgeCheckResult:
    is_ready = False
    badge = None
    issuer = None
    error = None

    def __init__(self, is_ready=False, badge=None, issuer=None, error=None):
        self.is_ready = is_ready
        self.issuer = issuer
        self.badge = badge
        self.error = error


def check_badge_is_ready_to_issue(user, course_key, block):
    course_id = str(course_key)

    num_attempt = 0
    max_attempts = 10

    badgr_enabled = org_badgr_enabled(course_key.org)
    if not badgr_enabled:
        return BadgeCheckResult(error='Issuing badges is disabled for this org')

    config = Configuration.get_config()
    issuer_entity_id = config.get_issuer_entity_id()
    if not issuer_entity_id:
        return BadgeCheckResult(error='Badge issuer is not found')

    issuer = Issuer.objects.filter(is_active=True, external_id=issuer_entity_id).first()
    if not issuer:
        return BadgeCheckResult(error='Badge issuer is not found')

    if block.category == 'sequential':
        seq_block = block
    else:
        seq_block = block.get_parent()

        while seq_block and num_attempt < max_attempts:
            if seq_block.category == 'sequential':
                break
            seq_block = seq_block.get_parent()
            num_attempt = num_attempt + 1

    if seq_block and seq_block.category == 'sequential':
        seq_block_id = str(seq_block.location)
        block_cache_obj = BlockCache.objects.filter(
            course_id=str(course_id), block_id=seq_block_id, field_name='badge_id').first()

        if block_cache_obj:
            badge = Badge.objects.filter(issuer=issuer, external_id=block_cache_obj.field_value, is_active=True).first()

            if badge:
                assertion = Assertion.objects.filter(
                    badge=badge, course_id=str(course_id), block_id=seq_block_id, user=user).first()

                if not assertion:
                    is_completed, blocks_ids = check_sequential_block_is_completed(
                        course_key, seq_block_id, user=user)

                    if is_completed:
                        conf = Configuration.get_config()
                        min_percentage = conf.get_min_percentage()
                        min_percentage = float(min_percentage) if min_percentage else 0

                        course = modulestore().get_course(course_key, depth=0)
                        course_grade = CourseGradeFactory().read(user, course)
                        mapped_usage_key = UsageKey.from_string(seq_block_id)
                        earned, possible = course_grade.score_for_block(mapped_usage_key)
                        if possible == 0:
                            weighted_score = 0
                        else:
                            weighted_score = float(earned) / float(possible)

                        if weighted_score > min_percentage:
                            return BadgeCheckResult(is_ready=True, badge=badge, issuer=issuer)
                        else:
                            err_msg = "Student's score is less than minimum (%s): %s" % (min_percentage, weighted_score)
                            return BadgeCheckResult(error=err_msg)

                    else:
                        return BadgeCheckResult(error='Quiz is not completed yet')

                else:
                    return BadgeCheckResult(error='Badge was already issued')

            else:
                return BadgeCheckResult(error='Badge Class is unavailable or not active')

        return BadgeCheckResult(error='Quiz is unavailable')

    return BadgeCheckResult(error='Can\'t find sequential block')


def issue_badge_assertion(user, course_key, block):
    config = Configuration.get_config()

    badge_res = check_badge_is_ready_to_issue(user, course_key, block)
    if badge_res.is_ready:
        with transaction.atomic():
            try:
                api_client = BadgrApi()
                result = api_client.create_user_assertion(user.email, badge_res.badge.external_id)

                assertion = Assertion(
                    external_id=result['entityId'],
                    user=user,
                    badge=badge_res.badge,
                    url=result['openBadgeId'],
                    image_url=result['image'],
                    course_id=str(course_key),
                    block_id=str(block.location)
                )
                assertion.save()

                import pprint
                pprint.pprint(result)

                badge_data = {
                    'badge_title': badge_res.badge.title,
                    'badge_description': badge_res.badge.description,
                    'badge_image_url': result['image'],
                    'badge_external_url': result['openBadgeId'],
                    'badgr_issuer_url': badge_res.issuer.url,
                    'badgr_issuer_image': badge_res.issuer.image_url,
                    'badgr_login_page': config.get_badgr_login_page()
                }

                return True, badge_data, None
            except Exception as exp:
                raise exp
                return False, None, str(exp)
    else:
        return False, None, badge_res.error

import json

from django.core.management import BaseCommand
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.content.block_structure.models import OraBlockStructure
from common.djangoapps.credo_modules.mongo import get_course_structure
from common.djangoapps.credo_modules.models import OraBlockScore, OraScoreType, AttemptCourseMigration
from django.conf import settings
from django.utils.html import strip_tags
from pymongo import MongoClient
from pymongo.database import Database
from openassessment.xblock.openassessmentblock import DEFAULT_RUBRIC_CRITERIA, DEFAULT_ASSESSMENT_MODULES
from lms.djangoapps.courseware.models import StudentModule
from submissions import api as sub_api
from openassessment.assessment.api import staff as staff_api
from openassessment.assessment.api import self as self_api
from openassessment.assessment.api import peer as peer_api
from opaque_keys.edx.keys import UsageKey
from common.djangoapps.student.models import AnonymousUserId


class Command(BaseCommand):

    _user_cache = {}

    def handle(self, *args, **options):
        connection = MongoClient(host=settings.CONTENTSTORE['DOC_STORE_CONFIG']['host'],
                                 port=settings.CONTENTSTORE['DOC_STORE_CONFIG']['port'])
        mongo_conn = Database(connection, settings.CONTENTSTORE['DOC_STORE_CONFIG']['db'])
        mongo_user = settings.CONTENTSTORE['DOC_STORE_CONFIG'].get("user")
        mongo_password = settings.CONTENTSTORE['DOC_STORE_CONFIG'].get("password")
        if mongo_user and mongo_password:
            mongo_conn.authenticate(mongo_user, mongo_password)
        definitions = mongo_conn.modulestore.definitions

        course_overviews = CourseOverview.objects.all().order_by('id')
        for course_overview in course_overviews:
            course_obj = AttemptCourseMigration.objects.filter(course_id=str(course_overview.id)).first()
            if not course_obj:
                self._process_course(course_overview.id, definitions)
                AttemptCourseMigration(course_id=str(course_overview.id), done=True).save()

    def _get_grader_id(self, scorer_id):
        if scorer_id in self._user_cache:
            return self._user_cache[scorer_id]
        anon = AnonymousUserId.objects.filter(anonymous_user_id=scorer_id).first()
        if anon:
            grader_id = anon.user_id
            self._user_cache[scorer_id] = grader_id
            return grader_id
        return None

    def _get_ora_block_score(self, score_type, assessment, course_id, org, block_id, module_item, ora_answer):
        res = []
        for part in assessment['parts']:
            ora_criterion_name = part['option']['criterion']['label'].strip().replace('|', '-')
            ora_option_label = part['option']['label'].strip()
            points_possible = part['option']['criterion']['points_possible']
            points_earned = part["option"]['points']

            res.append(OraBlockScore(
                course_id=course_id,
                org_id=org,
                block_id=block_id,
                user=module_item.student,
                answer=ora_answer,
                score_type=score_type,
                criterion=ora_criterion_name,
                option_label=ora_option_label,
                points_possible=points_possible,
                points_earned=points_earned,
                created=assessment['scored_at'],
                grader_id=self._get_grader_id(assessment['scorer_id'])
            ))
        return res

    def _process_course(self, course_key, definitions):
        org = course_key.org
        course = course_key.course
        run = course_key.run
        course_id = str(course_key)
        ora_blocks = OraBlockStructure.objects.filter(course_id=course_id)
        ora_blocks_dict = {o.block_id: o for o in ora_blocks}
        ora_to_insert = []
        grades_to_insert = []

        print('>>>>>> process course:', course_id)
        OraBlockScore.objects.filter(course_id=course_id, grader_id__isnull=True).delete()

        course_structure = get_course_structure(course_key)
        if course_structure:
            for block in course_structure['blocks']:
                if block['block_type'] == 'openassessment':
                    definition = definitions.find_one({'_id': block['definition']})
                    block_id = 'block-v1:%s+%s+%s+type@openassessment+block@%s' % (org, course, run, block['block_id'])
                    usage_key = UsageKey.from_string(block_id)
                    print('---- process block: ', block_id)
                    if definition:
                        ora_prompt = ''
                        ora_item = ora_blocks_dict.get(block_id)
                        if ora_item:
                            continue

                        criteria_points = {}
                        rubric_criteria = definition['fields'].get('rubric_criteria', DEFAULT_RUBRIC_CRITERIA)
                        for i, crit in enumerate(rubric_criteria):
                            crit_label = rubric_criteria[i]['label'].strip()
                            rubric_criteria[i]['label'] = crit_label
                            criteria_points[crit_label] = {}
                            for j, option in enumerate(crit['options']):
                                option_label = rubric_criteria[i]['options'][j]['label'].strip()
                                rubric_criteria[i]['options'][j]['label'] = option_label
                                criteria_points[crit_label][option_label] = option['points']

                        ora_rubric_criteria = json.dumps(rubric_criteria)
                        is_ora_empty_rubrics = len(rubric_criteria) == 0
                        support_multiple_rubrics = block['fields'].get('support_multiple_rubrics', False)
                        is_additional_rubric = block['fields'].get('is_additional_rubric', False)
                        display_rubric_step_to_students = block['fields'].get('display_rubric_step_to_students', False)
                        rubric_assessments = definition['fields'].get('rubric_assessments', DEFAULT_ASSESSMENT_MODULES)
                        ora_steps_lst = []
                        if not is_ora_empty_rubrics:
                            for step in rubric_assessments:
                                if step['name'] == 'peer-assessment':
                                    ora_steps_lst.append('peer')
                                elif step['name'] == 'self-assessment':
                                    ora_steps_lst.append('self')
                                elif step['name'] == 'staff-assessment':
                                    ora_steps_lst.append('staff')
                        ora_steps = json.dumps(sorted(ora_steps_lst))

                        if 'prompt' in definition['fields']:
                            try:
                                base_prompts = json.loads(definition['fields']['prompt'])
                            except ValueError:
                                base_prompts = [
                                    {
                                        'description': definition['fields']['prompt'],
                                    }
                                ]
                        else:
                            base_prompts = [
                                {
                                    'description': '--',
                                }
                            ]
                        prompts = []
                        brs_tags = ['<br>', '<br/>', '<br />']
                        for pr in base_prompts:
                            pr_descr = pr['description']
                            for br_val in brs_tags:
                                pr_descr = pr_descr.replace(br_val, "\n")
                            prompts.append(strip_tags(pr_descr).strip())

                        if len(prompts) > 1:
                            ora_prompt = "\n".join(prompts)
                        elif len(prompts) == 1:
                            ora_prompt = prompts[0]

                        ora_item = OraBlockStructure(
                            course_id=course_id,
                            org_id=org,
                            block_id=block_id,
                            is_ora_empty_rubrics=is_ora_empty_rubrics,
                            support_multiple_rubrics=support_multiple_rubrics,
                            is_additional_rubric=is_additional_rubric,
                            prompt=ora_prompt,
                            rubric_criteria=ora_rubric_criteria,
                            display_rubric_step_to_students=display_rubric_step_to_students,
                            steps=ora_steps
                        )
                        ora_to_insert.append(ora_item)

                        if is_ora_empty_rubrics:
                            continue

                        modules_raw_data = StudentModule.objects.filter(
                            course_id=course_key, module_state_key=usage_key, module_type='openassessment')
                        for module_item in modules_raw_data:
                            module_data = json.loads(module_item.state)
                            if 'submission_uuid' in module_data:
                                submission_uuid = module_data['submission_uuid']
                                submission = sub_api.get_submission_and_student(submission_uuid)
                                if not submission:
                                    continue
                                ora_answer_lst = []
                                for part in submission['answer']['parts']:
                                    ora_answer_lst.append(part['text'])
                                ora_answer = '\n'.join(ora_answer_lst)

                                for step in ora_steps_lst:
                                    if step == 'staff':
                                        staff_assessment = staff_api.get_latest_staff_assessment(submission_uuid)
                                        if staff_assessment:
                                            grades_to_insert.extend(
                                                self._get_ora_block_score(OraScoreType.STAFF, staff_assessment,
                                                                          course_id, org, block_id, module_item,
                                                                          ora_answer))
                                    elif step == 'self':
                                        self_assessment = self_api.get_assessment(submission_uuid)
                                        if self_assessment:
                                            grades_to_insert.extend(
                                                self._get_ora_block_score(OraScoreType.SELF, self_assessment, course_id,
                                                                          org, block_id, module_item, ora_answer))
                                    elif step == 'peer':
                                        assessments = peer_api.get_assessments(submission_uuid)
                                        if assessments:
                                            for peer_assessment in assessments:
                                                grades_to_insert.extend(
                                                    self._get_ora_block_score(OraScoreType.PEER, peer_assessment,
                                                                              course_id, org, block_id, module_item,
                                                                              ora_answer))

        if ora_to_insert:
            print('>>>>>> ora_to_insert:', len(ora_to_insert))
            OraBlockStructure.objects.bulk_create(ora_to_insert, batch_size=100)

        if grades_to_insert:
            print('>>>>>> grades_to_insert:', len(grades_to_insert))
            OraBlockScore.objects.bulk_create(grades_to_insert, batch_size=1000)

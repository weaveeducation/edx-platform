import json
from datetime import datetime
import pytz

from django.core.management import BaseCommand
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.content.block_structure.models import OraBlockStructure
from credo_modules.mongo import get_course_structure
from credo_modules.models import TrackingLog, OraBlockScore, OraScoreType, AttemptCourseMigration
from django.conf import settings
from django.utils.html import strip_tags
from pymongo import MongoClient
from pymongo.database import Database


class Command(BaseCommand):

    def handle(self, *args, **options):
        connection = MongoClient(host=settings.CONTENTSTORE['DOC_STORE_CONFIG']['host'],
                                 port=settings.CONTENTSTORE['DOC_STORE_CONFIG']['port'])
        mongo_conn = Database(connection, settings.CONTENTSTORE['DOC_STORE_CONFIG']['db'])
        mongo_conn.authenticate(settings.CONTENTSTORE['DOC_STORE_CONFIG']['user'],
                                settings.CONTENTSTORE['DOC_STORE_CONFIG']['password'])
        definitions = mongo_conn.modulestore.definitions

        course_overviews = CourseOverview.objects.all().order_by('id')
        for course_overview in course_overviews:
            course_obj = AttemptCourseMigration.objects.filter(course_id=str(course_overview.id)).first()
            if not course_obj:
                self._process_course(course_overview.id, definitions)

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
                    if definition:
                        ora_prompt = ''
                        ora_item = ora_blocks_dict.get(block_id)
                        if ora_item:
                            continue

                        criteria_points = {}
                        rubric_criteria = definition['fields']['rubric_criteria']
                        for i, crit in enumerate(rubric_criteria):
                            crit_label = rubric_criteria[i]['label'].strip()
                            rubric_criteria[i]['label'] = crit_label
                            criteria_points[crit_label] = {}
                            for j, option in enumerate(crit['options']):
                                option_label = rubric_criteria[i]['options'][j]['label'].strip()
                                rubric_criteria[i]['options'][j]['label'] = option_label
                                criteria_points[crit_label][option_label] = option['points']

                        ora_rubric_criteria = json.dumps(rubric_criteria)
                        is_ora_empty_rubrics = len(definition['fields']['rubric_criteria']) == 0
                        support_multiple_rubrics = block['fields'].get('support_multiple_rubrics', False)
                        is_additional_rubric = block['fields'].get('is_additional_rubric', False)
                        display_rubric_step_to_students = block['fields'].get('display_rubric_step_to_students', False)
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
                            display_rubric_step_to_students=display_rubric_step_to_students
                        )
                        ora_to_insert.append(ora_item)

                        ora_data = TrackingLog.objects.filter(
                            course_id=course_id, block_id=block_id,
                            is_last_attempt=1, is_ora_empty_rubrics=False, is_view=False
                        ).values('user_id', 'ora_criterion_name', 'grade', 'max_grade', 'answer', 'ora_answer', 'ts')

                        for ora_tracking_log in ora_data:
                            ora_criterion_name = ora_tracking_log['ora_criterion_name'].strip()
                            ora_option_label = ora_tracking_log['answer'].strip()
                            dt_object = datetime.fromtimestamp(ora_tracking_log['ts']).replace(tzinfo=pytz.utc)
                            if ora_criterion_name in criteria_points and ora_option_label in criteria_points[ora_criterion_name]:
                                grades_to_insert.append(OraBlockScore(
                                    course_id=course_id,
                                    org_id=org,
                                    block_id=block_id,
                                    user_id=ora_tracking_log['user_id'],
                                    answer=ora_tracking_log['ora_answer'],
                                    score_type=OraScoreType.STAFF,
                                    criterion=ora_criterion_name,
                                    option_label=ora_option_label,
                                    points_possible=int(ora_tracking_log['max_grade']),
                                    points_earned=criteria_points[ora_criterion_name][ora_option_label],
                                    created=dt_object
                                ))
                            else:
                                print('>>>>> ora_criterion_name not found')

        if ora_to_insert:
            print('>>>>>> ora_to_insert:', len(ora_to_insert))
            OraBlockStructure.objects.bulk_create(ora_to_insert, batch_size=100)

        if grades_to_insert:
            print('>>>>>> grades_to_insert:', len(grades_to_insert))
            OraBlockScore.objects.bulk_create(ora_to_insert, batch_size=1000)

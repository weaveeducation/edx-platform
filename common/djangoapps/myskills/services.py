from lms.djangoapps.courseware.utils import CREDO_GRADED_ITEM_CATEGORIES
from lms.djangoapps.grades.api import CourseGradeFactory
from xmodule.modulestore.django import modulestore
from .extended_progress import tags_student_progress, assessments_progress
from .utils import convert_into_tree


class MySkillsService:
    student = None
    course = None
    courseware_summary = None

    def __init__(self, student, course):
        self.student = student
        self.course = course

    def _get_course_problem_blocks(self):
        return modulestore().get_items(self.course.id, qualifiers={'category': {'$in': CREDO_GRADED_ITEM_CATEGORIES}})

    def _get_courseware_summary(self):
        if not self.courseware_summary:
            course_grade = CourseGradeFactory().read(self.student, self.course)
            self.courseware_summary = course_grade.chapter_grades.values()
        return self.courseware_summary

    def get_tags_summary(self):
        problem_blocks = self._get_course_problem_blocks()
        courseware_summary = self._get_courseware_summary()

        tags = tags_student_progress(self.course, self.student, problem_blocks, courseware_summary)
        tags_to_100 = sorted(tags, key=lambda k: "%03d_%s" % (k['percent_correct'], k['tag']))
        tags_from_100 = sorted(tags, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))

        context = {
            'top5tags': tags_from_100[:5],
            'lowest5tags': tags_to_100[:5],
        }
        return context

    def get_tags_all_data(self):
        problem_blocks = self._get_course_problem_blocks()
        courseware_summary = self._get_courseware_summary()

        tags = tags_student_progress(self.course, self.student, problem_blocks, courseware_summary, group_tags=True)
        tags_assessments = [v.copy() for v in tags if v['tag_is_last']]

        tags = convert_into_tree(tags)
        tags_assessments = sorted(tags_assessments, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))

        context = {
            'tags': tags,
            'tags_assessments': tags_assessments,
            'url_api_get_tag_data': '',
            'url_api_get_tag_section_data': '',
            'api_student_id': 0,
            'api_org': ''
        }
        return context

    def get_assessment_summary(self, include_data_str=True):
        courseware_summary = self._get_courseware_summary()
        assessments = assessments_progress(courseware_summary, include_data_str=include_data_str)
        return assessments

    def get_assessment_all_data(self):
        problems_dict = {}
        problem_blocks = self._get_course_problem_blocks()
        for pr in problem_blocks:
            parent = pr.get_parent()
            if parent is None:
                continue
            problems_dict[str(pr.location)] = {
                'display_name': pr.display_name,
                'vertical_id': None,
                'vertical_name': '',
                'hidden': False
            }
            if pr.category == 'openassessment':
                problems_dict[str(pr.location)]['hidden'] = pr.is_hidden()
            if parent.category == 'vertical':
                problems_dict[str(pr.location)]['vertical_id'] = str(parent.location)
                problems_dict[str(pr.location)]['vertical_name'] = parent.display_name
            else:
                parent = parent.get_parent()
                if parent.category == 'vertical':
                    problems_dict[str(pr.location)]['vertical_id'] = str(parent.location)
                    problems_dict[str(pr.location)]['vertical_name'] = parent.display_name
                else:
                    raise Exception("Can't find vertical block for element: " + str(pr.location))

        courseware_summary = self._get_courseware_summary()
        assessments = assessments_progress(courseware_summary, problems_dict)

        context = {
            'assessments': assessments
        }
        return context

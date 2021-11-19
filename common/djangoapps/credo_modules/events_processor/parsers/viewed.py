from .abstract import AbstractEventParser
from ..utils import EventCategory, CorrectData, combine_student_properties, ora_is_graded


class ViewedParser(AbstractEventParser):

    def _is_ora(self, event):
        category = event.get('event', {}).get('category')
        return category == 'openassessment'

    def parse(self, event_data):
        if self._is_ora(event_data):
            items = []
            rubrics = event_data.get('event', {}).get('rubrics', [])
            if rubrics:
                for part in rubrics:
                    criterion_name = part.get('label', None)
                    if criterion_name:
                        criterion_name = criterion_name.replace(":", " ")
                        item = self.process(event_data, rubric=part, criterion_name=criterion_name)
                        items.append(item)
                return items
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.viewed

    def is_ora_block(self, event, *args, **kwargs):
        return self._is_ora(event)

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        if self._is_ora(event):
            rubrics = event.get('event', {}).get('rubrics', [])
            if not rubrics:
                return True
        return False

    def get_ora_status(self, event, *args, **kwargs):
        if self._is_ora(event):
            return 'not_submitted'
        else:
            return None

    def custom_event_condition(self, event, *args, **kwargs):
        return True

    def get_possible_points(self, event, *args, **kwargs):
        rubric = kwargs.get('rubric')
        if self._is_ora(event) and rubric:
            return max([x['points'] for x in rubric['options']])
        return None

    def get_problem_id(self, event, *args, **kwargs):
        return event.get('event').get('usage_key')

    def get_correctness(self, event_data, *args, **kwargs):
        return CorrectData(False, 0, 1, None)

    def get_grade(self, correctness, *args, **kwargs):
        return 0

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        return 'No answer'

    def get_question_text(self, event, *args, **kwargs):
        return event.get('event').get('question_text', '').replace("\n", " ").replace("\t", " ").replace("\r", "").replace("|", " ")

    def get_display_name(self, event, *args, **kwargs):
        return event.get('event').get('display_name', '')

    def get_question_name(self, event, *args, **kwargs):
        display_name = self.get_display_name(event, *args, **kwargs)
        criterion_name = kwargs.get('criterion_name')
        if self._is_ora(event) and criterion_name:
            return display_name + ': ' + criterion_name.strip()
        return display_name

    def get_saved_tags(self, event, **kwargs):
        saved_tags = event.get('event').get('tagging_aside', {})
        return saved_tags

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_new_attempt(self, event, *args, **kwargs):
        return False

    def is_block_view(self, event, *args, **kwargs):
        return True

    def get_student_properties(self, event):
        tmp = event.get('event').get('student_properties_aside', {}).get('student_properties', {})
        return combine_student_properties(tmp)

    def get_graded(self, event, *args, **kwargs):
        if self._is_ora(event):
            return ora_is_graded(event)
        return None

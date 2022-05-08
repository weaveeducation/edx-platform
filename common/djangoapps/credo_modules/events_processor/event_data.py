import hashlib
from .utils import prepare_text_for_column_db, get_answer_from_text


class EventData:
    def __init__(self, category, course_id, org_id, course, run, block_id, block_tag_id,
                 timestamp, dtime, dtime_ts, saved_tags, student_properties,
                 grade, max_grade, user_id, display_name, question_name, question_text, question_text_hash,
                 answers, submit_info=None, is_ora_empty_rubrics=False, is_block_view=False, possible_points=None,
                 ora_block=False, ora_status=None, is_new_attempt=False, block_seq=None, criterion_name=None,
                 correctness=None, is_correct=False, term=None, answer_id=None,
                 prop_user_name=None, prop_user_email=None, ora_user_answer=None, graded=None):
        self.category = category
        self.course_id = course_id
        self.course = course
        self.org_id = org_id
        self.run = run
        self.block_id = block_id
        self.block_tag_id = block_tag_id
        self.timestamp = timestamp
        self.dtime_ts = dtime_ts
        self.dtime = dtime
        self.saved_tags = saved_tags
        self.student_properties = student_properties
        self.grade = grade
        self.max_grade = max_grade
        self.criterion_name = criterion_name
        self.correctness = correctness
        self.is_correct = is_correct
        self.user_id = user_id
        self.display_name = prepare_text_for_column_db(display_name, 500) if display_name else ""
        self.question_name = prepare_text_for_column_db(question_name, 2048) if question_name else ""
        self.question_text = question_text
        self.question_hash = None
        self.question_text_hash = question_text_hash
        if answers:
            answers_text = get_answer_from_text(answers)
            self.answers = prepare_text_for_column_db(answers_text)
        else:
            self.answers = ""
        self.answers_hash = None
        self.submit_info = submit_info
        self.is_ora_empty_rubrics = is_ora_empty_rubrics
        self.is_block_view = is_block_view
        self.possible_points = possible_points
        self.ora_block = ora_block
        self.ora_status = ora_status
        self.is_new_attempt = is_new_attempt
        self.block_seq = block_seq
        self.is_staff = False
        self.term = term
        self.answer_id = answer_id
        self.sequential_name = None
        self.sequential_id = None
        self.sequential_graded = False
        self.prop_user_name = prop_user_name
        self.prop_user_email = prop_user_email
        course_user_id_source = course_id + '|' + str(self.user_id)
        self.course_user_id = hashlib.md5(course_user_id_source.encode('utf-8')).hexdigest()
        self.ora_user_answer = prepare_text_for_column_db(ora_user_answer, 500) if ora_user_answer else None
        self.graded = graded

    def __str__(self):
        sb = []
        for key in self.__dict__:
            v = self.__dict__[key]
            sb.append(key + '=' + v)
        return '<EventData ' + ', '.join(sb) + '>'

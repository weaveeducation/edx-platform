from lms.djangoapps.courseware.models import StudentModule
from xmodule.modulestore.django import modulestore
from completion.models import BlockCompletion


def get_course_block_with_survey(course_key, supervisor_evaluation_xblock):
    sequential_blocks = modulestore().get_items(
        course_key, qualifiers={'category': 'sequential'}
    )
    for seq in sequential_blocks:
        if seq.use_as_survey_for_supervisor and seq.supervisor_evaluation_hash \
          and seq.supervisor_evaluation_hash == supervisor_evaluation_xblock.evaluation_block_unique_id:
            return seq

    return None


def copy_progress(course_key, block_keys, src_student, dst_student):
    StudentModule.objects.filter(course_id=course_key, module_state_key__in=block_keys, student=dst_student).delete()
    BlockCompletion.objects.filter(context_key=course_key, block_key__in=block_keys, user=dst_student).delete()

    modules = StudentModule.objects.filter(course_id=course_key, module_state_key__in=block_keys, student=src_student)
    for module in modules:
        module.pk = None
        module.student = dst_student
        module.save()

    completions = BlockCompletion.objects.filter(context_key=course_key, block_key__in=block_keys, user=src_student)
    for completion in completions:
        completion.pk = None
        completion.user = dst_student
        completion.save()

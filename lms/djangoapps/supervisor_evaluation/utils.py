from xmodule.modulestore.django import modulestore


def get_course_block_with_survey(course_key, supervisor_evaluation_xblock):
    sequential_blocks = modulestore().get_items(
        course_key, qualifiers={'category': 'sequential'}
    )
    for seq in sequential_blocks:
        if seq.use_as_survey_for_supervisor and seq.supervisor_evaluation_hash \
          and seq.supervisor_evaluation_hash == supervisor_evaluation_xblock.evaluation_block_unique_id:
            return seq

    return None

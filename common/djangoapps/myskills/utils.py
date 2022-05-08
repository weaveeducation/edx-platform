from submissions.api import get_submissions


def get_tag_title(tag):
    tag_parts = tag.split(' - ')
    if len(tag_parts) > 1:
        return ' > '.join(tag_parts[1:]).replace('"', '')
    else:
        return tag.replace('"', '')


def get_tag_title_short(tag):
    tag_parts = tag.split(' - ')
    if len(tag_parts) > 1:
        return tag_parts[-1].replace('"', '')
    else:
        return tag.replace('"', '')


def get_ora_submission_id(course_id, anonymous_user_id, block_id):
    student_item_dict = dict(
        course_id=str(course_id),
        student_id=anonymous_user_id,
        item_id=block_id,
        item_type='openassessment'
    )
    context = dict(**student_item_dict)
    submissions = get_submissions(context)
    if len(submissions) > 0:
        return submissions[0]
    return None


def get_tag_values(data, group_tags=False, tags_to_hide=None, tag_descriptions=None):
    res = []
    tags_used = []
    if not tags_to_hide:
        tags_to_hide = []
    if not tag_descriptions:
        tag_descriptions = {}

    if group_tags:
        for v in data:
            if v.startswith(tuple(tags_to_hide)):
                continue
            tag_split_lst = v.split(' - ')
            if len(tag_split_lst) > 1:
                for idx, tag_part in enumerate(tag_split_lst):
                    if idx > 0:
                        tag_new_val = ' - '.join(tag_split_lst[0:idx + 1])
                        if tag_new_val not in tags_used:
                            res.append({
                                'value': tag_new_val,
                                'num': idx - 1,
                                'is_last': (idx == (len(tag_split_lst) - 1)),
                                'id': tag_new_val,
                                'parent_id': ' - '.join(tag_split_lst[0:idx]) if idx > 1 else None,
                                'description': tag_descriptions.get(tag_new_val, '').replace('\n', ' ').replace('\r', '')
                            })
                            tags_used.append(tag_new_val)
            else:
                res.append({
                    'value': v,
                    'num': 0,
                    'is_last': True,
                    'id': v,
                    'parent_id': None,
                    'description': tag_descriptions.get(v, '').replace('\n', ' ').replace('\r', '')
                })
        return res
    else:
        for v in data:
            if v.startswith(tuple(tags_to_hide)):
                continue
            res.append({
                'value': v,
                'num': 0,
                'is_last': True,
                'id': v,
                'parent_id': None,
                'description': tag_descriptions.get(v, '').replace('\n', ' ').replace('\r', '')
            })
        return res


def _convert_into_tree_filter(_d):
    return {a: b for a, b in _d.items() if a != 'parent_id'}


def _sort_tree_node(tags):
    return sorted(tags, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag_title_short']))


def convert_into_tree(_d, _start=None):
    res = []
    for i in _d:
        if i['parent_id'] == _start:
            p = i.copy()
            p['children'] = convert_into_tree(_d, i['id'])
            res.append(_convert_into_tree_filter(p))
    return _sort_tree_node(res)


def get_student_name(student):
    student_name = student.first_name + ' ' + student.last_name
    student_name = student_name.strip()
    if student_name:
        student_name = student_name + ' (' + student.email + ')'
    else:
        student_name = student.email
    return student_name

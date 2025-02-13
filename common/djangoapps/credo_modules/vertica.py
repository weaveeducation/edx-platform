import csv
import os
import tempfile
import vertica_python
import time

from django.db import transaction
from django.conf import settings
from .models import TrackingLog


def get_vertica_dsn():
    return settings.VERTICA_DSN + '?connection_timeout=30'


def merge_data_into_vertica_table(model_class, update_process_num=None, ids_list=None,
                                  course_ids_lst=None, vertica_dsn=None, filter_fn=None,
                                  skip_delete_step=False, delimiter=None):

    if settings.DEBUG:
        print('It is debug mode. Skip merge')
        return

    table_name = model_class._meta.db_table
    if not delimiter:
        delimiter = '|'

    print('Get data from DB to save into CSV')
    if update_process_num:
        model_data = model_class.objects.filter(update_process_num=update_process_num).values_list()
    elif ids_list:
        model_data = model_class.objects.filter(id__in=ids_list).values_list()
    elif course_ids_lst:
        model_data = model_class.objects.filter(course_id__in=course_ids_lst).values_list()
    else:
        raise Exception('Please specify "update_process_num", "ids_list" or "course_ids_lst" param')

    if len(model_data) == 0:
        print('Nothing to copy!')
        return

    fields = []
    for field in model_class._meta.get_fields():
        if field.name == 'block':
            fields.append('block_id')
        else:
            fields.append(field.name)

    insert_columns = ['%s' % field for field in fields]
    insert_columns_sql = ','.join(insert_columns)

    table_name_copy_from = table_name + '_temp'

    dsn = vertica_dsn if vertica_dsn else get_vertica_dsn()
    additional_settings = {}
    #if settings.VERTICA_BACKUP_SERVER_NODES:
    #    additional_settings['backup_server_node'] = settings.VERTICA_BACKUP_SERVER_NODES

    with vertica_python.connect(dsn=dsn, **additional_settings) as conn:
        cursor = conn.cursor()

        sql0 = 'TRUNCATE TABLE %s' % table_name_copy_from
        print(sql0)
        cursor.execute(sql0)

        tf = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv')
        print('Save CSV into file: %s' % tf.name)

        csvwriter = csv.writer(tf, delimiter=delimiter)
        new_rows_num = 0

        for model_item in model_data:
            if filter_fn:
                ignore_res = filter_fn(model_item, fields)
                if ignore_res:
                    continue

            row_to_insert = []
            for v in model_item:
                if isinstance(v, str):
                    row_to_insert.append(v.strip().replace("\n", " ").replace("\t", " ")
                                         .encode("utf-8").decode('ascii', errors='ignore'))
                elif isinstance(v, bool):
                    row_to_insert.append('1' if v else '0')
                elif v is None:
                    row_to_insert.append('')
                else:
                    row_to_insert.append(str(v))
            csvwriter.writerow(row_to_insert)
            new_rows_num = new_rows_num + 1
        tf.close()

        if new_rows_num == 0:
            print('Nothing to insert/update')
            os.remove(tf.name)
            return

        print('Try to insert/update %d rows' % new_rows_num)

        print('Vertica COPY operation')
        try:
            with open(tf.name, "r") as fs:
                sql1 = "COPY %s (%s) FROM STDIN DELIMITER '%s' ABORT ON ERROR"\
                       % (table_name_copy_from, insert_columns_sql, delimiter)
                print(sql1)
                cursor.copy(sql1, fs, buffer_size=65536)
            os.remove(tf.name)
        except Exception:
            os.remove(tf.name)
            raise

        if not skip_delete_step:
            print('Vertica DELETE operation')
            if course_ids_lst:
                sql2 = "DELETE FROM %s WHERE course_id in (SELECT DISTINCT course_id FROM %s)"\
                       % (table_name, table_name_copy_from)
            else:
                sql2 = "DELETE FROM %s WHERE id in (SELECT id FROM %s)" % (table_name, table_name_copy_from)
            print(sql2)
            t1 = time.time()
            cursor.execute(sql2)
            t2 = time.time()
            print('Vertica DELETE done: %s sec' % str(t2 - t1))

        print('Vertica INSERT operation')
        sql3 = "INSERT INTO %s SELECT * FROM %s" % (table_name, table_name_copy_from)
        print(sql3)
        t3 = time.time()
        cursor.execute(sql3)
        t4 = time.time()
        print('Vertica INSERT done: %s sec' % str(t4 - t3))

        cursor.execute("COMMIT")


def update_data_in_vertica(vertica_conn, where_condition, update_condition):
    if not isinstance(where_condition, dict) or 'org_id' not in where_condition:
        raise Exception('org_id must be set in the WHERE fields')

    if not update_condition or not isinstance(update_condition , dict):
        raise Exception('update_condition is not set')

    update_fields_lst = list(update_condition.copy())
    update_condition_vertica = {}
    select_fields = list(update_condition.keys())
    select_fields.append('id')

    for update_field, update_val in update_condition.items():
        if isinstance(update_val, str):
            update_condition_vertica[update_field] = "'" + update_val.strip().replace("\n", " ").replace("\t", " ")\
                .replace("'", '').encode("utf-8").decode('ascii', errors='ignore') + "'"
        elif isinstance(update_val, bool):
            update_condition_vertica[update_field] = '1' if update_val else '0'
        else:
            update_condition_vertica[update_field] = str(update_val)

    limit = 1000
    id_from = 0
    id_to = id_from + limit
    process = True

    while process:
        data = TrackingLog.objects.filter(**where_condition).order_by('id').values(*select_fields)[id_from:id_to]
        len_items = len(data)

        if not len_items:
            process = False
        else:
            id_from = id_from + limit
            id_to = id_to + limit

            ids_to_update = []
            for v in data:
                for update_field in update_fields_lst:
                    if v[update_field] != update_condition[update_field]:
                        ids_to_update.append(v['id'])
                        break

            if ids_to_update:
                where_condition_res = []
                for where_field, where_val in where_condition.items():
                    where_condition_res.append(where_field + "='" + where_val + "'")
                where_condition_res.append('id IN (' + ','.join([str(id_upd) for id_upd in ids_to_update]) + ')')

                update_condition_vertica_res = []
                for update_field, update_val in update_condition_vertica.items():
                    update_condition_vertica_res.append(update_field + '=' + update_val)

                sql = "UPDATE credo_modules_trackinglog SET " \
                      + ', '.join(update_condition_vertica_res) + ' WHERE ' + ' AND '.join(where_condition_res)

                where_condition_copy = where_condition.copy()
                where_condition_copy['id__in'] = ids_to_update

                with transaction.atomic():
                    TrackingLog.objects.filter(**where_condition_copy).update(**update_condition)
                    cursor = vertica_conn.cursor()
                    cursor.execute(sql)
                    cursor.execute("COMMIT")

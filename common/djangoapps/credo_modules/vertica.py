import csv
import os
import tempfile
import vertica_python
import time

from django.conf import settings


def get_vertica_dsn():
    return settings.VERTICA_DSN + '?connection_timeout=30'


def merge_data_into_vertica_table(model_class, update_process_num=None, ids_list=None,
                                  course_ids_lst=None, vertica_dsn=None, filter_fn=None):
    table_name = model_class._meta.db_table

    print('Get data from DB to save into CSV')
    if update_process_num:
        model_data = model_class.objects.filter(update_process_num=update_process_num).values_list()
    elif ids_list:
        model_data = model_class.objects.filter(id__in=ids_list).values_list()
    elif course_ids_lst:
        model_data = model_class.objects.filter(course_id__in=course_ids_lst).values_list()
    else:
        raise Exception('Please specify "update_process_num" or "course_ids_lst" param')

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

    with vertica_python.connect(dsn=dsn) as conn:
        cursor = conn.cursor()

        sql0 = 'TRUNCATE TABLE %s' % table_name_copy_from
        print(sql0)
        cursor.execute(sql0)

        tf = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        print('Save CSV into file: %s' % tf.name)

        csvwriter = csv.writer(tf, delimiter='|')
        new_rows_num = 0

        for model_item in model_data:
            if filter_fn:
                ignore_res = filter_fn(model_item, fields)
                if ignore_res:
                    continue

            row_to_insert = []
            for v in model_item:
                if isinstance(v, str):
                    row_to_insert.append(v.strip().replace("\n", " ").replace("\t", " ").encode("utf-8"))
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
            with open(tf.name, "rb") as fs:
                sql1 = "COPY %s (%s) FROM STDIN DELIMITER '|' ABORT ON ERROR"\
                       % (table_name_copy_from, insert_columns_sql)
                print(sql1)
                cursor.copy(sql1, fs, buffer_size=65536)
            os.remove(tf.name)
        except Exception:
            os.remove(tf.name)
            raise

        print('Vertica DELETE operation')
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

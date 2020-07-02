import csv
import os
import tempfile
import vertica_python

from django.conf import settings


def get_vertica_dsn():
    return settings.VERTICA_DSN


def merge_data_into_vertica_table(table_name, model_class, update_process_num, vertica_dsn=None):
    print('Get data from DB to save into CSV')
    model_data = model_class.objects.filter(update_process_num=update_process_num).values_list()
    if len(model_data) == 0:
        print('Nothing to copy!')
        return

    table_name_copy_from = table_name + '_temp'
    dsn = get_vertica_dsn()
    if not dsn:
        dsn = vertica_dsn
    dsn = dsn + '?connection_timeout=30'

    with vertica_python.connect(dsn=dsn) as conn:
        cursor = conn.cursor()

        sql0 = 'TRUNCATE TABLE %s' % table_name
        print(sql0)
        cursor.execute(sql0)

        print('Save CSV into file')
        tf = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        csvwriter = csv.writer(tf, delimiter='|')
        csvwriter.writerows(model_data)
        tf.close()

        print('Vertica COPY operation')
        try:
            with open(tf.name, "rb") as fs:
                sql1 = "COPY %s FROM STDIN DELIMITER '|'" % table_name_copy_from
                print(sql1)
                cursor.copy(sql1, fs, buffer_size=65536)
            os.remove(tf.name)
        except Exception:
            os.remove(tf.name)
            raise

        fields = [field.name for field in model_class._meta.get_fields()]

        update_columns = ['%s=t1.%s' % (field, field) for field in fields if fields != 'id']
        update_columns_sql = ','.join(update_columns)

        insert_columns = ['%s' % field for field in fields]
        insert_columns_sql = ','.join(insert_columns)

        insert_values = ['t1.%s' % field for field in fields]
        insert_values_sql = ','.join(insert_values)

        sql2 = "MERGE INTO %s AS t2 USING %s AS t1 ON t1.id = t2.id " +\
               "WHEN MATCHED THEN UPDATE SET %s " +\
               "WHEN NOT MATCHED THEN INSERT %s VALUES (%s)"
        sql2 = sql2 % (table_name, table_name_copy_from, update_columns_sql,
                       insert_columns_sql, insert_values_sql)

        print('Vertica MERGE operation')
        print(sql2)
#        cursor.execute(sql2)
#        cursor.execute("COMMIT")

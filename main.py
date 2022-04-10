import time
from datetime import datetime
import psycopg2


def main():
    i = 0
    while True:
        try:
            client = psycopg2.connect(
                dbname='postgres',
                user='postgres',
                password='toor',
                host='192.168.1.121,192.168.1.122',
                port=5432,
                connect_timeout=2
            )
            cursor = client.cursor()
            cursor.execute("SELECT * FROM guestbook;")
            data = cursor.fetchall()
            cursor.close()
            client.close()

            print("%02d %s %s" % (i, datetime.now(), data[-1::]))
        except Exception as e:
            print("%02d %s %s" % (i, datetime.now(), e))

        i += 1
        time.sleep(1)


if __name__ == '__main__':
    main()

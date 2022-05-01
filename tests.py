import random
import time
import psycopg2
import asyncio


def insert(i: int):
    while True:
        try:
            delay = random.random()*2
            time.sleep(delay)
            client = psycopg2.connect(
                dbname='postgres',
                user='postgres',
                password='toor',
                host='192.168.1.121,192.168.1.122',
                port=5432,
                connect_timeout=2
            )
            cursor = client.cursor()
            cursor.execute(
                f"INSERT INTO guestbook (visitor_email, date, message) "
                f"VALUES ('hernya@urfu.ru', current_date, 'Test AAA');"
            )
            cursor.close()
            client.commit()
            client.close()

            print("[+] Запрос #%d выполнен (задержка %.2f сек)..." % (i, delay))
            break
        except Exception as e:
            print("[-] Повторный запуск запроса #%d (%s)" % (i, str(e).strip()))


async def make_requests():
    loop = asyncio.get_event_loop()
    futures = [
        loop.run_in_executor(None, insert, i) for i in range(3_000)
    ]

    for future in futures:
        await future


def main():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(make_requests())


if __name__ == '__main__':
    main()

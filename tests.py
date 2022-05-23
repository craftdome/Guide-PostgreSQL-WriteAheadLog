import random
import time
from threading import Thread
import psycopg2.errors

import psycopg2
import asyncio


sended_requests = 0
max_requests = 1_000
hosts = [
    "192.168.1.177",
    "192.168.1.98"
]


def execute_sql(host: str, sql: str) -> bool:
    try:
        client = psycopg2.connect(
            dbname='testdb',
            user='kronos',
            password='toor',
            host=host,
            port=5432,
            connect_timeout=3
        )
        cursor = client.cursor()
        cursor.execute(sql)
        cursor.close()
        client.commit()
        client.close()
        return True
    except psycopg2.InternalError as _e:
        return False


def insert(i: int):
    delay = random.random()*2
    time.sleep(delay)

    j = 0
    while True:
        try:
            response = execute_sql(hosts[j], f"INSERT INTO users (info) VALUES ('Info {i}');")
            if not response:
                j = (j + 1) % len(hosts)
                continue

            break
        except Exception as e:
            print("[-] Повторный запуск запроса #%d (%s)" % (i, str(e).strip()))


async def make_requests():
    global sended_requests, max_requests

    loop = asyncio.get_event_loop()
    futures = [
        loop.run_in_executor(None, insert, i) for i in range(max_requests)
    ]

    for future in futures:
        await future
        sended_requests += 1


def counter():
    while True:
        print("[+] Прогресс %.3f%% (%d/%d)" % (float(sended_requests/max_requests) * 100, sended_requests, max_requests))
        if sended_requests == max_requests:
            break
        time.sleep(5)


def main():
    loop = asyncio.get_event_loop()

    Thread(target=counter).start()

    loop.run_until_complete(make_requests())


if __name__ == '__main__':
    main()

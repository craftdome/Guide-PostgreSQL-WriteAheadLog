import os
import re
import shutil
import time
import traceback
from datetime import datetime
import sys
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from urllib.error import URLError

import psycopg2

log_file = Path("/var/log/wal.log")
conf_file = Path("/etc/postgresql/11/main/postgresql.conf")
wal_trigger_file = Path("/tmp/wal_trigger.file")
data_folder = "/var/lib/postgresql/11"
witness_url = "https://ya.ru"

replica_credentials = {
    "dbname": 'postgres',
    "user": 'postgres',
    "password": 'toor',
    "host": '',
    "port": 5432
}


def print_log(*msgs, end='\n'):
    msgs = [
        msg
            .replace("StandBy", "\033[1;33mStandBy\033[0m")
            .replace("Primary", "\033[1;32mPrimary\033[0m")
        for msg in msgs
    ]
    print("%s\t" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *msgs, end=end)


def internet_is_up() -> bool:
    for timeout in [3, 5, 10, 15]:
        print_log("* Проверка доступности сети %s (ожидание ответа %dс)..." % (witness_url, timeout))
        try:
            r: HTTPResponse = urllib.request.urlopen(witness_url, timeout=timeout)
            print_log("* Ответ получен %s -> %d" % (witness_url, r.status))
            return True
        except URLError as e:
            print_log("* Связь отсутствует:", e)
    else:
        return False


def is_read_only() -> bool:
    # Чтение содержимого конфига
    with conf_file.open("r") as f:
        conf_content: str = f.read()
        f.close()

    # Поиск параметра в конфиге через regex
    match = re.search(r"^(default_transaction_read_only = off)$", conf_content, re.M)
    match2 = re.search(r"^(default_transaction_read_only = on)$", conf_content, re.M)
    if not match and not match2:
        print_log("Для корректной работы раскомментируйте параметр 'default_transaction_read_only = off'")

    return match is None


def set_read_only(mode: bool):
    on_line = "default_transaction_read_only = on"
    off_line = "default_transaction_read_only = off"

    try:
        # Чтение содержимого конфига
        with conf_file.open("r") as f:
            conf_content: str = f.read()
            f.close()

        # Переключение режима read_only
        if mode:
            conf_content = conf_content.replace(off_line, on_line, 1)
        else:
            conf_content = conf_content.replace(on_line, off_line, 1)

        # Запись содержимого конфига
        with conf_file.open("w") as f:
            f.write(conf_content)
            f.close()
    except Exception as _e:
        pass


def replica_connection_test() -> bool:
    try:
        psycopg2.connect(
            dbname=replica_credentials['dbname'],
            user=replica_credentials['user'],
            password=replica_credentials['password'],
            host=replica_credentials['host'],
            port=replica_credentials['port'],
            connect_timeout=10
        ).close()
        return True
    except Exception as _e:
        return False


def replica_is_read_only() -> bool:

    try:
        client = psycopg2.connect(
            dbname=replica_credentials['dbname'],
            user=replica_credentials['user'],
            password=replica_credentials['password'],
            host=replica_credentials['host'],
            port=replica_credentials['port'],
            connect_timeout=10
        )
        cursor = client.cursor()
        cursor.execute("SHOW default_transaction_read_only;")
        value = cursor.fetchone()[0]
        cursor.close()

        return value == "on"
    except Exception as _e:
        return False


def make_replication():
    print_log("* Началась репликация данных с %s..." % replica_credentials["host"])
    shutil.rmtree(data_folder + "/main_old")
    print_log("| Каталог %s удалён " % data_folder + "/main_old")
    os.rename(data_folder + "/main", data_folder + "/main_old")
    print_log("| Каталог %s переименован в %s" % (data_folder + "/main", data_folder + "/main_old"))
    os.system(
        f'su - postgres -c "pg_basebackup -h {replica_credentials["host"]} -D {data_folder}/main '
        f'-U repuser -w --wal-method=stream >& /dev/null"'
    )
    print_log("| Выполнена команда репликации pg_basebackup")

    # Включаем postgresql
    os.system("systemctl restart postgresql")
    print_log("* Перезапускаем postgresql")


def main(argv):
    global replica_credentials
    replica_credentials['host'] = argv[2]

    # Поток вывода в файл
    sys.stdout = log_file.open("a")

    try:

        # Проверяем доступность сети
        if internet_is_up():
            # Существует ли триггер-файл (был ли зафиксирован сбой)?
            if wal_trigger_file.exists():
                # Производим репликацию
                make_replication()

                # Удаляем триггер-файл, созданный после сбоя
                wal_trigger_file.unlink(missing_ok=True)
                print_log("* Триггер-файл %s удалён" % wal_trigger_file.name)
            else:

                # Проверяем связь с другой БД
                print_log("* Проверка связи с другой БД (host=%s)... " % replica_credentials['host'], end="")
                if replica_connection_test():
                    print("OK")
                    # ЭТАП DEMOTE

                    # Решение конфликтов, когда обе БД работают в одном режиме
                    time.sleep(int(argv[1]))
                    # StandBy - StandBy
                    if replica_is_read_only():
                        if is_read_only():
                            print_log("* Похоже, что обе БД работают в режиме StandBy (read-only)")
                            set_read_only(False)
                            print_log("* Переход в режим работы Primary (read-write)")
                        else:
                            # В этом случае мы не должны реплицировать данные, так как мы Primary
                            # То есть просто завершаем работу скрипта
                            pass
                    else:
                        # Primary - Primary
                        if not is_read_only():
                            # Если мы Primary, то понижаем себя
                            print_log("* Похоже, что обе БД работают в режиме Primary (read-write)")
                            set_read_only(True)
                            print_log("* Переход в режим работы StandBy (read-only)")

                        # Производим репликацию
                        make_replication()
                else:
                    print("FAILED")
                    # ЭТАП PROMOTE

                    # Связь с другой БД отсутствует
                    if is_read_only():
                        # Включение режима read-write
                        set_read_only(False)
                        print_log("* Переход в режим работы Primary (read-write)")
                        # Рестарт БД
                        os.system("systemctl restart postgresql")
                        print_log("* Перезапуск postgresql")

                print_log("* Текущее состояние:", "StandBy" if is_read_only() else "Primary")
        else:

            # Сеть недоступна
            # Если триггер-файла о сбое не существует
            if not wal_trigger_file.exists():
                os.system("systemctl stop postgresql")
                print_log("* Выключение postgresql")
                set_read_only(True)
                print_log("| Включен режим \"read-only\"")
                wal_trigger_file.touch(0o777)
                print_log("* Триггер-файл %s создан" % wal_trigger_file.absolute().resolve())

    except Exception as e:
        print_log("КРАШ СКРИПТА:", e)
        traceback.print_last()


if __name__ == '__main__':
    main(sys.argv)

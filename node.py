import os
import time
from typing import Optional, Tuple

import psycopg2
import requests
from urllib.error import URLError

from logger import Log
from node_settings import arbiter_url, self_node_settings, arbiter_ip, replication_user


class Node:
    def __init__(self, json: dict):
        self.dbname = json['dbname']
        self.user = json['user']
        self.passowrd = json['password']
        self.host = json['host']
        self.slot_name = json['slot_name']
        self.port = json.get('port', 5432)

    def __get_connection(self, connect_timeout):
        return psycopg2.connect(
                dbname=self.dbname,
                user=self.user,
                password=self.passowrd,
                host=self.host,
                port=self.port,
                connect_timeout=connect_timeout
        )

    def connection_test(self, connect_timeout=10) -> bool:
        try:
            self.__get_connection(connect_timeout).close()
            return True
        except Exception as _e:
            return False

    def pg_is_in_recovery(self, connect_timeout=10) -> bool:
        try:
            client = self.__get_connection(connect_timeout)
            cursor = client.cursor()
            cursor.execute("SELECT pg_is_in_recovery();")
            data = cursor.fetchone()
            cursor.close()
            client.close()
            return data[0]
        except Exception as _e:
            return False

    def drop_replication_slot(self, slot_name: str, connect_timeout=10) -> bool:
        try:
            client = self.__get_connection(connect_timeout)
            cursor = client.cursor()
            cursor.execute("SELECT pg_drop_replication_slot('%s');" % slot_name)
            cursor.close()
            client.close()
            return True
        except Exception as _e:
            return False


class Arbiter:

    @classmethod
    def reached(cls) -> bool:
        for timeout in [5, 10, 15]:
            try:
                r = requests.get(arbiter_url + "/test_connection", timeout=timeout)
                return r.status_code == 200
            except Exception as _e:
                pass
        else:
            return False

    @classmethod
    def who_is_primary(cls, timeout=10) -> Tuple[int, Optional[Node]]:
        r = requests.get(arbiter_url + "/who_is_primary", timeout=timeout)

        if r.status_code not in [200, 201, 202]:
            return r.status_code, None

        return r.status_code, Node(r.json())

    @classmethod
    def ping(cls) -> bool:
        return os.system("ping -c 4 %s" % arbiter_ip) == 0


class Worker:
    primary_node: Optional[Node]
    self_node: Optional[Node]

    must_be_primary = False
    failover = False

    @classmethod
    def reached(cls) -> bool:
        for timeout in [3, 5, 10, 15]:
            try:
                return cls.primary_node.connection_test(timeout)
            except URLError as _e:
                pass
        else:
            return False

    @classmethod
    def stop_db(cls) -> bool:
        rc = os.system('~/pg_ctl -D ~/db stop')
        if rc != 0:
            Log.ERROR.print("* Ошибка при выключении БД: rc =", rc)
            return False
        return True

    @classmethod
    def start_db(cls) -> bool:
        rc = os.system('~/pg_ctl -D ~/db start -l log_db')
        if rc != 0:
            Log.ERROR.print("* Ошибка при включении БД: rc =", rc)
            return False
        return True

    @classmethod
    def promote(cls) -> bool:
        rc = os.system('~/pg_ctl -D ~/db promote')
        if rc != 0:
            Log.ERROR.print("* Ошибка при выполнении promote: rc =", rc)
            return False
        return True

    @classmethod
    def create_replication_slot_to_primary(cls) -> bool:
        # На случай если слот уже был создан, удаляем его
        cls.primary_node.drop_replication_slot(cls.self_node.slot_name)

        # Производим репликацию
        rc = os.system("~/pg_basebackup -h %s -p %d -U %s --create-slot --slot=%s --write-recovery-conf -D ~/db" % (
            cls.primary_node.host, cls.primary_node.port, replication_user, cls.self_node.slot_name
        ))

        if rc != 0:
            Log.ERROR.print("* Ошибка при создании слота репликации: rc =", rc)
            return False
        return True

    @classmethod
    def recreate_replication_to_primary(cls) -> bool:
        # Остановлена ли БД?
        if cls.pg_isready():
            Log.ERROR.print("* БД ещё работает, нельзя перенастроить репликацию!")
            return False

        # Удалить старую БД
        os.system("rm -rf ~/db_old")

        # Переименовать текущую БД
        os.system("mv ~/db ~/db_old")

        # Создать слот репликации на новый Primary
        return cls.create_replication_slot_to_primary()

    @classmethod
    def pg_isready(cls) -> bool:
        return os.system("~/pg_isready -h %s -p %d -d %s -U %s --quiet" % (
            cls.self_node.host, cls.self_node.port, cls.self_node.dbname, cls.self_node.user
        )) == 0


def setup(first_start=False):
    # Установка своих настроек
    Worker.self_node = Node(self_node_settings)

    # Запрашиваем у сервера актуальный Primary
    status_code, node = Arbiter.who_is_primary()
    Log.INFO.print("* Арбитр сообщил код:", status_code)

    if status_code == 200:  # Назначен новый Primary
        Log.INFO.print("| Флаг: Worker.must_be_primary = False")
        Worker.must_be_primary = False
        Log.INFO.print("| Обновляем информацию, назначен новый Primary: %s" % node.host)
        Worker.primary_node = node

        # Если я был StandBy и перенастройка не нужна
        if not first_start and not Worker.recreate_replication_to_primary():
            Log.ERROR.print("* Ошибка при выполнении Worker.recreate_replication_to_primary()")

    elif status_code == 201:  # Вас назначили новым Primary
        Log.INFO.print("| Флаг: Worker.must_be_primary = True")
        Worker.must_be_primary = True
        Log.INFO.print("| Обновляем информацию, теперь мы Primary")
        Worker.primary_node = Worker.self_node

    elif status_code == 202:  # Я всё ещё Primary
        Log.INFO.print("| Флаг: Worker.must_be_primary = True")
        Worker.must_be_primary = True
        Log.INFO.print("| Обновляем информацию, мы всё ещё Primary")
        Worker.primary_node = Worker.self_node

    else:
        Log.ERROR.print("| Арбитр -> status:%d" % status_code)

    # Запускаем БД
    Log.INFO.print("| Запускаем БД... ", end="")
    if not Worker.pg_isready():
        Log.print_ok()
        Worker.start_db()
    else:
        Log.print_already()
        Log.WARN.print("| БД уже была запущена")

    # Проверяем статус pg_is_in_recovery
    if Worker.must_be_primary:
        if Worker.self_node.pg_is_in_recovery():
            Log.WARN.print("* БД работает в режиме StandBy, а должна быть Primary, выполняем promote...")
            Worker.promote()
    else:
        if not Worker.self_node.pg_is_in_recovery():
            Log.WARN.print("* БД работает в режиме Primary, а должна быть StandBy, выполняем demote...")
            Worker.stop_db()
            Log.WARN.print("| Пересоздаём слот репликации на %s" % Worker.primary_node.host)
            Worker.recreate_replication_to_primary()
            Worker.start_db()


def main():
    setup(first_start=True)

    # Запускаем штатный процесс работы
    Log.INFO.print("* Запуск мониторинга (%s)" % ("Primary" if Worker.must_be_primary else "StandBy"))
    while True:
        time.sleep(5)

        # Отрабатываем сбой
        if Worker.failover:
            if Arbiter.reached():
                Log.FAILOVER.print("* Арбитр доступен, произодим восстановление...")
                setup()
                # Фух, восстановились...
                Log.FAILOVER.print("* Флаг Worker.failover = False")
                Worker.failover = False
            else:
                Log.FAILOVER.print("* Арбитр недоступен")
                continue

        # я Primary
        if Worker.must_be_primary:
            Log.INFO.print("* Проверка связи с Арбитром... (я Primary) ", end="")

            if Arbiter.reached() or Arbiter.ping():
                Log.print_ok()
            else:
                Log.print_failed()
                Log.FAILOVER.print("| Зафиксирован сбой (нет связи с Арбитром)...")
                # Выключаем БД
                Log.FAILOVER.print("| Выключаем БД...")
                Worker.stop_db()
                Worker.failover = True

        # я StandBy
        else:
            # Проверяем связь с Primary
            Log.INFO.print("* Проверка связи с Primary... (я StandBy) ", end="")
            if Worker.reached():
                Log.print_ok()
            else:
                Log.print_failed()
                Log.FAILOVER.print("| Зафиксирован сбой (нет связи с Primary)...")
                # Выключаем БД
                Log.FAILOVER.print("| Выключаем БД...")
                Worker.stop_db()
                Worker.failover = True


if __name__ == '__main__':
    main()

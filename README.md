# Подготовка
Демо: https://youtu.be/yNkXkKOghTU

Для развёртывания стенда выбран дистрибутив linux `debian-10.10.0-amd64`.
Для работы скрипта HA кластера на серверах БД должен быть установлен python версии 3.8 или новее.

Этапы
1. Создание двух виртуальных машин (ВМ):
	* **pgsql-1** 
	* **pgsql-2**
2. Начальная сетевая конфигурация ВМ

| Сервер | IP-адрес | Маска | Шлюз |
| --- | :---: | :---: | :---: |
| pgsql-1  | 192.168.1.121 | 24 | 192.168.1.1 |
| pgsql-2  | 192.168.1.122 | 24 | 192.168.1.1 |

> Все настройки выполняются от пользователя root

# Установка пакетов
Пакеты сетевых инструментов и postgresql
```
apt install net-tools postgresql
```

# Настройка PGSQL-Primary
1. Создание пользователя для репликации базы данных (БД) 
```
su - postgres -с "createuser -U postgres repuser -P -c 5 --replication"
```
2. Конфигурация в **pg_hba.conf**
```
host replication	repuser		192.168.1.122/32	trust
host all		postgres	192.168.1.0/24		trust # Для тестирования подключения к БД из локальной сети
```
3. Конфигурация в **postgresql.conf**
```
listen_addresses = '*'
default_transaction_read_only = off
```

# Настройка PGSQL-Standby
1. Конфигурация в **pg_hba.conf**
```
host replication	repuser		192.168.1.121/32	trust
host all		postgres	192.168.1.0/24 		trust # Для тестирования подключения к БД из локальной сети
```
2. Конфигурация в **postgresql.conf**
```
listen_addresses = '*'
default_transaction_read_only = on
```
3. Меняем название БД, для дальнейшей репликации с PGSQL-Primary
```
mv /var/lib/postgresql/11/main/ /var/lib/postgresql/11/main_old/
```
4. Остановка службы postgresql
```
systemctl stop postgresql
```
5. Репликация каталога main с PGSQL-Primary на PGSQL-Standby
```
su - postgres -c "pg_basebackup -h 192.168.2.11 -D /var/lib/postgresql/11/main/ -U repuser -w --wal-method=stream"
```
6. Запуск службы postgresql
```
systemctl start postgresql
```

# Написание скриптов
1. Скрипт wal.py выполняет проверку работы серверов БД в кластере и ставится на оба сервера кластера.

# Расписание запуска скриптов в crontab (PGSQL-Primary)
1. Копирование файла wal.py в /usr/local/bin/wal.py для простоты активации скрипта через команду `python3.9 wal.py`
```
cp /root/wal.py /usr/local/bin/wal.py
```
2. Добавление задачи в планировщик через команду `crontab -e` (_запуск каждую минуту с задержкой 0 секунд и проверкой IP 192.168.1.122_)
```
* * * * * root python3.9 /usr/local/bin/wal.py 0 192.168.1.122
```

# Расписание запуска скриптов в crontab (PGSQL-Standby)
1. Копирование файла wal.py в /usr/local/bin/wal.py для простоты активации скрипта через команду `python3.9 wal.py`
```
cp /root/wal.py /usr/local/bin/wal.py
```
2. Добавление задачи в планировщик через команду `crontab -e` (_запуск каждую минуту с задержкой 10 секунд и проверкой IP 192.168.1.121_)
```
* * * * * root python3.9 /usr/local/bin/wal.py 10 192.168.1.121
```
# Скрипт для проверки подключения (Python 3.8)
1. Для работы скрипта необходимо установить пароль на пользователя postgres
```
su - postgres && psql
ALTER USER postgres WITH PASSWORD 'toor';
```
2. Скрипт **main.py**
```python
import time
from datetime import datetime
import psycopg2


def main():
    sql = "SELECT * FROM guestbook;"

    i = 0
    while True:
        try:
            client = psycopg2.connect(
                dbname='postgres',
                user='postgres',
                password='toor',
                host='192.168.1.124',
                port=5432,
                connect_timeout=5
            )
            cursor = client.cursor()
            cursor.execute(sql)
            data: list = cursor.fetchall()
            cursor.close()

            print("%02d %s %s" % (i, datetime.now(), data))
        except Exception as _e:
            print("%02d %s %s" % (i, datetime.now(), "База данных недоступна"))

        i += 1
        time.sleep(1)


if __name__ == '__main__':
    main()

```
3. Запуск скрипта `python main.py`

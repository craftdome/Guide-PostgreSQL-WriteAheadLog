# Подготовка
Демо: https://youtu.be/yNkXkKOghTU

Для развёртывания стенда выбран дистрибутив linux `debian-10.10.0-amd64`.
Для работы скрипта High Availability кластера на серверах должен быть установлен `python 3.8` или новее.

Этапы
1. Создание двух виртуальных машин (ВМ):
	* **pgsql-1** 
	* **pgsql-2**
2. Начальная сетевая конфигурация ВМ

| Сервер | IP-адрес | Маска | Шлюз |
| --- | :---: | :---: | :---: |
| **PGSQL-1**  | 192.168.1.121 | 24 | 192.168.1.1 |
| **PGSQL-2**  | 192.168.1.122 | 24 | 192.168.1.1 |

> Все настройки выполняются от пользователя `root`

# Установка пакетов
Пакеты сетевых инструментов и `postgresql`
```
apt install net-tools postgresql
```

# Настройка PGSQL-1
1. Создание пользователя для репликации базы данных (БД) 
```
su - postgres -с "createuser -U postgres repuser -P -c 5 --replication"
```
2. Конфигурация в `pg_hba.conf`
```
host replication	repuser		192.168.1.122/32	trust
# Для тестирования подключения к БД из локальной сети
host all		postgres	192.168.1.0/24		trust
```
3. Конфигурация в `postgresql.conf`
```
listen_addresses = '*'
default_transaction_read_only = off
```

# Настройка PGSQL-2
1. Конфигурация в `pg_hba.conf`
```
host replication	repuser		192.168.1.121/32	trust
# Для тестирования подключения к БД из локальной сети
host all		postgres	192.168.1.0/24 		trust
```
2. Конфигурация в `postgresql.conf`
```
listen_addresses = '*'
default_transaction_read_only = on
```
3. Меняем название БД, для дальнейшей репликации с **PGSQL-1**
```
mv /var/lib/postgresql/11/main/ /var/lib/postgresql/11/main_old/
```
4. Остановка службы `postgresql`
```
systemctl stop postgresql
```
5. Репликация каталога `/var/lib/postgresql/11/main/` с **PGSQL-1** на **PGSQL-2**
```
su - postgres -c "pg_basebackup -h 192.168.1.121 -D /var/lib/postgresql/11/main/ -U repuser -w --wal-method=stream"
```
6. Запуск службы `postgresql`
```
systemctl start postgresql
```

# Написание скриптов
1. Скрипт `wal.py` выполняет проверку работы серверов БД в кластере и ставится на оба сервера кластера
https://github.com/Tyz3/PostgreSQL-WriteAheadLog/blob/dca871a16c56a00c9f584d95709cd9e8ad18fe01/wal.py#L1-L226

> В задачу скрипта входит обнаружение отсутствия связи с Primary нодой и повышением себя до Primary, а также репликация данных с Primary ноды на  StandBy.

> Скрипт самостоятельно определяет статус локальной БД и "реплики", также решает конфликты, когда оба сервера могут могут стать StandBy или Primary одновременно.

> Процесс репликации, повышения/понижения и решения конфликтов отображается в лог-файле `/var/log/wal.log`
# Расписание запуска скрипта в crontab (PGSQL-1)
1. Расположение файла `wal.py` в `/root` с командой запуска `python3.9 /root/wal.py <sleep_before_work> <replica_ip>`
2. Добавление задачи в планировщик через команду `crontab -e` (_запуск каждую минуту с задержкой 0 секунд и проверкой IP 192.168.1.122_)
```
* * * * *	root	python3.9 /root/wal.py 0 192.168.1.122
```

# Расписание запуска скрипта в crontab (PGSQL-2)
1. Расположение файла `wal.py` в `/root` с командой запуска `python3.9 /root/wal.py <sleep_before_work> <replica_ip>`
2. Добавление задачи в планировщик через команду `crontab -e` (_запуск каждую минуту с задержкой 10 секунд и проверкой IP 192.168.1.121_)
```
* * * * *	root	python3.9 /root/wal.py 10 192.168.1.121
```

# Скрипт для моделирования внешнего подключения к кластеру (Python 3.8)
1. Для работы скрипта необходимо установить пароль для пользователя `postgres`
```
su - postgres && psql
ALTER USER postgres WITH PASSWORD 'toor';
```
2. Скрипт `main.py`
https://github.com/Tyz3/PostgreSQL-WriteAheadLog/blob/dca871a16c56a00c9f584d95709cd9e8ad18fe01/main.py#L1-L33


# Нагрузочное тестирование отказоустойчивого кластера PostreSQL
1. Для осуществления нагрузочного тестирования написан скрипт на Python `tests.py`
https://github.com/Tyz3/PostgreSQL-WriteAheadLog/blob/33162da855d84b3f690138c4fa29898a01723257/tests.py#L1-L51
2. Нагрузочное тестирование состоит из нескольких этапов:
> Отправка SQL-запросов `INSERT` Primary серверу отказоустойчивого кластера PostgreSQL;

> Отключение питания Primary серверу кластера PostgreSQL во время отправки SQL-запросов;

> Смена роли StandBy сервера кластера PostgreSQL на Primary;

> Отправка SQL-запросов новому Primary серверу кластера PostgreSQL;

> Отключение нового Primary сервера и включение старого сервера кластера PostgreSQL во время отправки SQL-запросов;

> Приём оставшихся SQL-запросов на старый Primary сервер кластера PostgreSQL.


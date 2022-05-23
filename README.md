# Подготовка
Демо: https://youtu.be/QqwcjC2qty0

Для развёртывания стенда выбран дистрибутив linux `debian-11.3.0-amd64`.
Для работы скрипта High Availability кластера на серверах должен быть установлен `python 3.10` или новее.

1. Создание двух виртуальных машин (ВМ):
    * **pgsql-1** 
    * **pgsql-2**
    * **Арбитр**
2. Начальная сетевая конфигурация ВМ

| Сервер             |   IP-адрес    | Маска | Шлюз |
|--------------------|:-------------:| :---: | :---: |
| **PGSQL-1** (ВМ)   | 192.168.1.177 | 24 | 192.168.1.1 |
| **PGSQL-2** (ВМ)   | 192.168.1.98  | 24 | 192.168.1.1 |
| **Arbiter** (хост) | 192.168.1.133 | 24 | 192.168.1.1 |

> Все настройки выполняются от пользователя `user`

# Установка PostgreSQL 14
Выполняется для всех ВМ.
```shell
sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -
apt update && apt -y install postgresql-14
```

# Основная настройка Primary
1. Создаём пустой кластер.
```shell
./initdb ~/db
```
2. Настройка `~/db/postgresql.conf`. Для сокета нужно создать соответствующую директорию `mkdir ~/socket`.
```editorconfig
listen_addresses = '*'
port = 5432
# Меняем расположение сокет-файла, чтобы БД запускалась от лица user
unix_socket_directories = '/home/user/socket'
```
3. Настройка `~/db/pg_hba.conf`. Добавляем в конец следующие строки.
```
host    all             kronos          192.168.1.0/24          trust
host    replication     repuser         192.168.1.0/24          trust
```
4. Запуск кластера `~/db`.
```shell
./pg_ctl -D ~/db start
```
5. Создаём пользователя для подключения и работы с БД `kronos` (`-s` права суперпользователя) и для репликации `repuser` (`-c 10` максимальное кол-во подключений).
```shell
./createuser kronos -P -s
./createuser -U kronos -P -c 10 --replication repuser
```
6. Создаём базу данных с названием `testdb`.
```shell
./createdb --owner=kronos testdb
```
7. Выдаём все права на БД `testdb` пользователю `kronos` (нужно сделать, есть это не суперпользователь).
```shell
./psql -h 192.168.1.177 --dbname=testdb -c "grant all privileges on database testdb to kronos;"
```
# Дополнительные настройки Primary
```shell
./psql --dbname=testdb -c "ALTER SYSTEM SET synchronous_standby_names to '*'"
./psql --dbname=testdb -c "SELECT pg_reload_conf();"
./psql --dbname=testdb -c "SET synchronous_commit to on;"
```
# Основная настройка StandBy
Если 192.168.1.177 будет Primary:
```shell
./pg_basebackup -h 192.168.1.177 -U repuser --create-slot --slot=rep98 --write-recovery-conf -D ~/db
```
Если 192.168.1.98 будет Primary:
```shell
./pg_basebackup -h 192.168.1.98 -U repuser --create-slot --slot=rep177 --write-recovery-conf -D ~/db
```

# Скрипты
Скрипт `node.py` выполняет проверку работы серверов БД в кластере и ставится на все сервера в кластере.
https://github.com/Tyz3/PostgreSQL-WriteAheadLog/blob/f716822cf96d0cd537c630e20205efd8b10edc21/node.py#L1-L275

Настройки скрипта лежат в файле `node_settings.py` с говорящими названиями (`host` и `slot_name` заменить для каждой БД).
https://github.com/Tyz3/PostgreSQL-WriteAheadLog/blob/f716822cf96d0cd537c630e20205efd8b10edc21/node_settings.py#L1-L12

> Файлы проекта: node.py, node_settings.py, logger.py

Скрипт `arbiter.py` выполняет роль наблюдателя, все "ноды" запрашивают актуальную информацию по состоянию кластера, получив ответ - принимают решение по дальнейшему режиму работы.
https://github.com/Tyz3/PostgreSQL-WriteAheadLog/blob/f716822cf96d0cd537c630e20205efd8b10edc21/arbiter.py#L1-L146

Настройки скрипта лежат в файле `arbiter_settings.py` с говорящими названиями.
https://github.com/Tyz3/PostgreSQL-WriteAheadLog/blob/f716822cf96d0cd537c630e20205efd8b10edc21/arbiter_settings.py#L1-L22

> Файлы проекта: arbiter.py, arbiter_settings.py

# Автозапуск скриптов через crontab
Рассмотрим пример с `node.py`. Закидываем файл `node.py` в `~/node` и добавляем задачу в планировщик через команду `crontab -e` (_запуск команды при старте системы_).
```
@reboot		user	python /home/user/node.py
```
Другие скрипты запускать аналогично. Либо вручную `python /home/user/node.py`.

# Скрипт для моделирования внешнего подключения к кластеру
https://github.com/Tyz3/PostgreSQL-WriteAheadLog/blob/f716822cf96d0cd537c630e20205efd8b10edc21/tests.py#L1-L85

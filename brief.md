## Общие команды
# Установка
sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -
apt update && apt -y install postgresql-14

# Бинарники postgres
cd /usr/lib/postgresql/14/bin

`./initdb ~/db`					создать пустой кластер

`./pg_isready`					проверить работу кластера

`./pg_ctl -D ~/db start`		запустить кластер

`./pg_basebackup`				сделать копию кластера

`./psql --port=5432 postgres`	подсоединиться к кластеру

## Предварительные настройки Primary
```./initdb ~/db
./pg_ctl -D ~/db start```

# Создаём юзеров
```./createuser kronos -P -s
./createuser -U kronos -P -c 10 --replication repuser```

# Создаём БД
```./createdb --owner=kronos testdb```

# Выдаём права на БД для юзера
```./psql --dbname=testdb -c "grant all privileges on database testdb to kronos;"```

# Primary - Включаем синхронную репликацию
```
./psql testdb -c "ALTER SYSTEM SET synchronous_standby_names to '*'"
./psql testdb -c "SELECT pg_reload_conf();"
./psql testdb -c "SET synchronous_commit to on;"
```

# Standby - Создаём слот репликации БД с Primary
```./pg_basebackup -h 192.168.1.177 -U repuser --create-slot --slot=rep98 --write-recovery-conf -D ~/db```

# Проверка режима работы
```./psql testdb -c "SELECT pg_is_in_recovery();"```

# Повышение Standby до Primary
```./pg_ctl -D ~/db promote```

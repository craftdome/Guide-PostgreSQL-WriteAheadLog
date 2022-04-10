# Подготовка
Демо: https://youtu.be/yNkXkKOghTU

Для развёртывания стенда выбран дистрибутив linux `debian-10.10.0-amd64`.

Этапы
1. Создание двух 2-х виртуальных машин (ВМ), на каждой 2 сетевых интерфейса
	* **ens33** - внешний (для доступа в сеть Интернет)
	* **ens35** - служебный (для взаимодействия ВМ между собой)
2. Начальная сетевая конфигурация ВМ

**PGSQL-Primary**
| Интерфейс | IP-адрес | Маска | Шлюз |
| --- | :---: | :---: | :---: |
| ens33  | 192.168.1.124 | 24 | 192.168.1.1 |
| ens35  | 192.168.2.11 | 24 |  |

**PGSQL-Standby**
| Интерфейс | IP-адрес | Маска | Шлюз |
| --- | :---: | :---: | :---: |
| ens33  | 192.168.1.65 | 24 | 192.168.1.1 |
| ens35  | 192.168.2.12 | 24 |  |

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
host replication	repuser		192.168.2.11/32	trust
host replication	repuser		192.168.2.12/32	trust
host all		postgres	192.168.1.0/24	trust # Для тестирования подключения к БД из локальной сети
```
3. Конфигурация в **postgresql.conf**
```
listen_addresses = '*'
```

# Настройка PGSQL-Standby
1. Конфигурация в **pg_hba.conf**
```
host replication	repuser		192.168.2.11/32	trust
host replication	repuser		192.168.2.12/32	trust
host all		postgres	192.168.1.0/24 	trust # Для тестирования подключения к БД из локальной сети
```
2. Меняем название БД, для дальнейшей репликации с PGSQL-Primary
```
mv /var/lib/postgresql/11/main/ /var/lib/postgresql/11/main_old/
```
3. Остановка службы postgresql
```
systemctl stop postgresql
```
4. Репликация каталога main с PGSQL-Primary на PGSQL-Standby
```
su - postgres -c "pg_basebackup -h 192.168.2.11 -D /var/lib/postgresql/11/main/ -U repuser -w --wal-method=stream"
```
5. Запуск службы postgresql
```
systemctl start postgresql
```

# Написание скриптов
1. Скрипт репликации для **PGSQL-Standby** (HA_standby.sh)

```bash
#!/bin/bash

#ps - переменная статуса postgresql на дополнительном сервере БД (1 - вкл, 0 - выкл)
#fl - переменная статуса порта 5432 на основном сервере БД (10 - открыт и доступен, 3 - недоступен)
#Если fl = 3 и ps = 1, то основной сервер недоступен, а postgresql на дополнительном работает -> выход из скрипта
#Если fl = 10 и ps = 0, то основной сервер доступен, а postgresql на дополнительном не работает -> репликация каталога /data с основного на дополнительный
#Если fl = 3 и ps = 0, то основной сервер недоступен, а postgresql на дополнительном не работает -> включение второго интерфейса и Postgresql на дополнительном
#Если fl = 10 и ps = 1, то основной сервер доступен, а postgresql на дополнительном работает -> репликация с дополнительного на основной каталога /data, отключение postgresql и второго интерфейса на дополнительном

#Ожидание перед завершением работы скрипта на PGSQL-Primary
sleep 10

#Декларирование переменных
declare -i ps
declare -i fl
DATA_FOLDER="/var/lib/postgresql/11"

#Проверяем состояние службы postgresql на резервном сервере, если работает ps=1, иначе 0
systemctl is-active postgresql > /dev/null 2>&1 && let "ps = 1" || let "ps = 0"

iface='192.168.2.11' # IP адрес основного сервера (PGSQL-Primary/ens35)

#Проверяем доступность порта 5432 на основном сервере, если доступен fl=10, иначе 1
(echo > /dev/tcp/$iface/5432) >& /dev/null && let "fl = 10" || let "fl = 0"

#Цикл проверки доступности порта 5432 на основном сервере каждые 10 секунд проверяем доступность
while [[ $fl -lt 3 ]]
do
	sleep 10; (echo > /dev/tcp/$iface/5432) >& /dev/null && let "fl = 10" || let "fl = $fl + 1"	
done

#Получаем сумму двух параметров, на которые ориентируемся
let "sum = $fl + $ps"

#Case по суммам параметров (см. параметры выше)
case $sum in
	3)
	systemctl start postgresql; ifconfig ens33 up; 
	echo "$(date) Primary dead, starting reserve... (event 3)" >> /var/log/HA_standby.log; exit 0;;

	4)
	echo "$(date) Primary dead, reserve working, waiting... (event 4)" >> /var/log/HA_standby.log; exit 0;;

	10)
	rm -rf $DATA_FOLDER/main_old && mv $DATA_FOLDER/main $DATA_FOLDER/main_old
	su - postgres -c "pg_basebackup -h $iface -D $DATA_FOLDER/main/ -U repuser -w --wal-method=stream >& /dev/null"; 
	echo "$(date) Primary alive, replicating of /data from primary to reserve... (event 10)">> /var/log/HA_standby.log; exit 0;;

	11)
	systemctl stop postgresql; ifconfig ens33 down; 
	echo "$(date) Primary alive, shutting down reserve... (event 11)">> /var/log/HA_standby.log; exit 0;;
esac
```
2. Скрипт для **PGSQL-Primary** (HA_primary.sh)
```bash
#!/bin/bash

#Значения параметров
#fl = 10 - сеть доступна
#fl = 3 - сеть недоступна
#ps = 1 - служба работает
#ps = 0 - служба не работает

declare -i ps
declare -i fl
DATA_FOLDER="/var/lib/postgresql/11"
#Проверяем состояние службы postgresql на основном сервере, если работает ps=1, иначе 0
systemctl is-active postgresql>/dev/null 2>&1 && let "ps = 1" || let "ps = 0"

IP=("8.8.8.8") # IP какой-нибудь машины для проверки доступа в интернет
fl=0
pattern="0 received"
#Проверяем доступность сети
while [[ $fl -lt 3 ]]
do
	result=$(ping -c 2 -W 1 -q $IP | grep transmitted)
	if [[ $result =~ $pattern || $? -ne 0 ]]; then
		sleep 10;let "fl = $fl + 1"	 
	else
		let "fl = 10"
	fi
done

#Получаем сумму двух параметров, на которые ориентируемся
let "sum = $fl + $ps"

#Case по суммам параметров (см. параметры выше)
case $sum in

	# Служба на основном сервере не работает, сеть недоступна
	3)
	echo "$(date) Primary dead, waiting...( event 3 )" >> /var/log/HA_master.log;exit 0;;
	# Служба на основном сервере работает, сеть доступна
	4)
	echo "$(date) Primary dead, stopping postgresql... (event 4)" >> /var/log/HA_master.log;systemctl stop postgresql; exit 0;;
	# Служба не работает, сеть доступна
	10)
	rm -rf $DATA_FOLDER/main_old && mv $DATA_FOLDER/main $DATA_FOLDER/main_old
	su - postgres -c "pg_basebackup -h 192.168.2.12 -D $DATA_FOLDER/main/ -U repuser -w --wal-method=stream >& /dev/null"; systemctl start postgresql; 
	echo "$(date) Primary alive, starting postgresql... (event 10)" >> /var/log/HA_master.log;exit 0;;
	# Служба работает, сеть доступна
	11)
	echo "$(date) Primary alive, waiting... (event 11)" >> /var/log/HA_master.log;exit 0;;
esac
```

> Скрипт HA_standby.sh каждую минуту проверяет доступность сервера PGSQL-Primary на порту 5432, если сервер отвечает, то интерфейс ens33 остаётся выключенным и производится репликация данных, иначе производится включение PGSQL-Standby (т.е. включение интерфейса ens33 и postgresql).

> Скрипт HA_primary.sh каждую минуту проверяет доступность сети пингом на внешний узел (8.8.8.8), если сеть недоступна, то производится выключение postgresql. Если служба postgresql выключена, а сеть доступна, то производится бэкап данных и запуск postgresql.

# Расписание запуска скриптов в crontab (PGSQL-Primary)
1. Копирование файла HA_primary.sh в /usr/local/bin/HA_primary для простоты активации скрипта через команду `HA_primary`
```
cp /root/HA_primary.sh /usr/local/bin/HA_primary
```
2. Добавление задачи в планировщик через команду `crontab -e` (_запуск каждую минуту_)
```
* * * * * root /usr/local/bin/HA_primary
```

# Расписание запуска скриптов в crontab (PGSQL-Standby)
1. Копирование файла HA_standby.sh в /usr/local/bin/HA_standby для простоты активации скрипта через команду `HA_standby`
```
cp /root/HA_standby.sh /usr/local/bin/HA_standby
```
2. Добавление задачи в планировщик через команду `crontab -e` (_запуск каждую минуту_)
```
* * * * * root /usr/local/bin/HA_standby
```

# Финальная настройка сети
1. После всех настроек выше, необходимо изменить ip-адреса у интерфейсов **ens35** на одинаковые, например, на 192.168.1.124

**PGSQL-Primary**
| Интерфейс | IP-адрес | Маска | Шлюз |
| --- | :---: | :---: | :---: |
| ens33  | 192.168.1.124 | 24 | 192.168.1.1 |
| ens35  | 192.168.2.11 | 24 |  |

**PGSQL-Standby**
| Интерфейс | IP-адрес | Маска | Шлюз |
| --- | :---: | :---: | :---: |
| ens33  | **192.168.1.124** | 24 | 192.168.1.1 |
| ens35  | 192.168.2.12 | 24 |  |

2. Перезагрузить сеть `systemctl restart networking`

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

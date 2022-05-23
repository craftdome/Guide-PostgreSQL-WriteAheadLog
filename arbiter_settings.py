from typing import List

# Конфигурация
listen_address = ("192.168.1.133", 5400)
db_nodes: List[dict] = [
    {
        "dbname": "testdb",
        "user": "kronos",
        "password": "toor",
        "host": "192.168.1.177",
        "slot_name": "rep177",
        "port": 5432
    },
    {
        "dbname": "testdb",
        "user": "kronos",
        "password": "toor",
        "host": "192.168.1.98",
        "slot_name": "rep98",
        "port": 5432
    }
]

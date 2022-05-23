
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, List, Tuple

import psycopg2

from arbiter_settings import listen_address, db_nodes


class Node:
    def __init__(self, dbname: str, user: str, password: str, host: str, slot_name: str, port=5432):
        self.dbname = dbname
        self.user = user
        self.passowrd = password
        self.host = host
        self.slot_name = slot_name
        self.port = port
        self.primary = False

    def connection_test(self) -> bool:
        try:
            psycopg2.connect(
                dbname=self.dbname,
                user=self.user,
                password=self.passowrd,
                host=self.host,
                port=self.port,
                connect_timeout=10
            ).close()
            return True
        except Exception as _e:
            return False

    def pg_is_in_recovery(self, connect_timeout=10) -> bool:
        try:
            client = psycopg2.connect(
                dbname=self.dbname,
                user=self.user,
                password=self.passowrd,
                host=self.host,
                port=self.port,
                connect_timeout=connect_timeout
            )
            cursor = client.cursor()
            cursor.execute("SELECT pg_is_in_recovery();")
            data = cursor.fetchone()
            cursor.close()
            client.close()
            return data[0]
        except Exception as _e:
            return False

    def __eq__(self, other) -> bool:
        return self.host == other

    def __str__(self):
        return '{"host":"%s", "port":%d, "dbname":"%s", "user":"%s", "password":"%s", "slot_name": "%s"}' % (
            self.host, self.port, self.dbname, self.user, self.passowrd, self.slot_name
        )


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    def send(self, status_code, content=None, content_type="application/json"):
        self.send_response(status_code)
        self.send_header('Content-type', content_type)
        self.end_headers()
        if content is not None:
            self.wfile.write(content.encode("UTF-8"))

    def do_GET(self):
        client_ip = self.client_address[0]

        if self.path.startswith("/test_connection"):
            self.send(200)
        elif self.path.startswith("/who_is_primary"):
            status_code, node = Arbiter.who_is_primary(client_ip)
            self.send(status_code, str(node))
        elif self.path.startswith("/am_i_standby"):
            status_code = Arbiter.am_i_standby(client_ip)
            self.send(status_code)
        else:
            self.send(404)


class Arbiter:
    nodes: List[Node] = []

    @classmethod
    def get_node_by_ip(cls, ip: str) -> Node:
        # Поиск первого совпадения
        node, = [node for node in cls.nodes if ip == node.host]

        return node

    @classmethod
    def get_primary(cls) -> Optional[Node]:
        for node in cls.nodes:
            if node.primary:
                return node
        else:
            return None

    @classmethod
    def who_is_primary(cls, client_ip: str) -> Tuple[int, Node]:
        primary = cls.get_primary()

        if primary.host == client_ip:
            return 202, primary

        if primary.connection_test():
            return 200, primary
        else:
            primary.primary = False
            node = cls.get_node_by_ip(client_ip)
            node.primary = True
            return 201, node

    @classmethod
    def am_i_standby(cls, client_ip: str) -> int:
        node = cls.get_node_by_ip(client_ip)

        return 404 if node.primary else 200


def main():
    for db_node in db_nodes:
        node = Node(
            db_node['dbname'],
            db_node['user'],
            db_node['password'],
            db_node['host'],
            db_node['slot_name'],
            db_node.get('port', 5432)
        )
        Arbiter.nodes.append(node)

    # Первая нода в списке по умолчанию будет Primary
    Arbiter.nodes[0].primary = True

    httpd = HTTPServer(listen_address, SimpleHTTPRequestHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()

import argparse
from contextlib import closing, contextmanager
from dataclasses import dataclass
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import socket
import sqlite3
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen


class ApiError(Exception):
    def __init__(self, status, code, **details):
        super().__init__(code)
        self.status = status
        self.body = {'error': code, **details}


class DropResponse(Exception):
    pass


def identifier(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value) is None:
        raise ValueError('invalid identifier')
    return value


def positive_id(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError('expected a positive integer identity')
    return value


def path_id(value):
    if len(value) > 19 or not value.isascii() or not value.isdecimal():
        raise ValueError('invalid numeric path identity')
    return positive_id(int(value))


def connect(database):
    db = sqlite3.connect(database, isolation_level=None, timeout=3.0)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def initialize(database, *schemas):
    with closing(connect(database)) as db:
        if db.execute('PRAGMA journal_mode = WAL').fetchone()[0] != 'wal':
            raise RuntimeError('service databases require SQLite WAL mode')
        db.executescript('\n'.join(schemas))


def database_busy(error):
    code = getattr(error, 'sqlite_errorcode', None)
    return code is not None and (code & 0xff) == sqlite3.SQLITE_BUSY


@contextmanager
def transaction(db, *, immediate=True):
    db.execute('BEGIN IMMEDIATE' if immediate else 'BEGIN')
    try:
        yield
        db.commit()
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise


def request_json(base_url, method, path, data=None, *, desk_key=None):
    headers = {'Accept': 'application/json'}
    if desk_key is not None:
        headers['Authorization'] = f'Bearer {desk_key}'
    body = None
    if data is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    request = Request(base_url.rstrip('/') + path, data=body, headers=headers, method=method)
    try:
        response = urlopen(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


@dataclass
class ServiceContext:
    database: str
    peer_url: str
    desk_key: str
    hooks: object = None


class FestivalServer(ThreadingHTTPServer):
    def __init__(self, port, handler, context):
        self.context = context
        super().__init__(('127.0.0.1', port), handler)

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_port}'


class JsonHandler(BaseHTTPRequestHandler):
    max_body_bytes = 16 * 1024 * 1024

    @property
    def context(self):
        return self.server.context

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.handle_json('GET')

    def do_POST(self):
        self.handle_json('POST')

    def read_body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= self.max_body_bytes:
            raise ApiError(413, 'invalid_body_size')
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError('expected a JSON object')
        return data

    def public_route(self, method, parts):
        return False

    def handle_json(self, method):
        try:
            parts = tuple(unquote(part) for part in urlsplit(self.path).path.strip('/').split('/'))
            if not self.public_route(method, parts):
                actual = self.headers.get('Authorization', '').encode('utf-8')
                expected = f'Bearer {self.context.desk_key}'.encode('utf-8')
                if not compare_digest(actual, expected):
                    raise ApiError(403, 'desk_key_required')
            data = self.read_body() if method == 'POST' else None
            with closing(connect(self.context.database)) as db:
                status, result = self.dispatch(db, method, parts, data)
        except DropResponse:
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        except ApiError as error:
            status, result = error.status, error.body
        except (KeyError, ValueError, RecursionError):
            status, result = 422, {'error': 'invalid_request'}
        except sqlite3.OperationalError as error:
            if not database_busy(error):
                raise
            status, result = 503, {'error': 'database_busy'}
        raw = json.dumps(result, ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


@contextmanager
def running(server):
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()


def run_service(factory):
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--peer', required=True)
    parser.add_argument('--desk-key', required=True, type=identifier)
    args = parser.parse_args()
    peer = urlsplit(args.peer)
    if (peer.scheme != 'http' or peer.hostname != '127.0.0.1' or peer.port is None
            or peer.path not in ('', '/') or peer.username or peer.query or peer.fragment):
        parser.error('--peer must be a loopback HTTP origin with a port')
    with factory(args.db, args.peer, args.desk_key, port=args.port) as server:
        print(server.url, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

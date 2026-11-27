"""Start both festival desks for a local API session."""
from argparse import ArgumentParser
from pathlib import Path
from tempfile import TemporaryDirectory

from editorial.http_api import serve_editorial
from festival_http import running
from release.http_api import serve_release
from samples.demo import DESK_KEY


def main():
    parser = ArgumentParser()
    parser.add_argument('--host', required=True, choices=('127.0.0.1',))
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    with TemporaryDirectory(prefix='festival-api-') as directory:
        root = Path(directory)
        with serve_editorial(root / 'editorial.sqlite3', '', DESK_KEY) as editorial:
            with serve_release(root / 'release.sqlite3', editorial.url, DESK_KEY, port=args.port) as release:
                editorial.context.peer_url = release.url
                with running(editorial):
                    print(f'editorial={editorial.url} release={release.url}', flush=True)
                    try:
                        release.serve_forever()
                    except KeyboardInterrupt:
                        pass


if __name__ == '__main__':
    main()

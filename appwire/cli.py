import argparse
import json
from pathlib import Path
import sys
from . import client
from .config import MAX_CONFIG, parse, profile_name


def main():
    parser = argparse.ArgumentParser(description='AppWire: per-app WireGuard, without host routing changes')
    sub = parser.add_subparsers(dest='op', required=True)
    sub.add_parser('list')
    for op in ('start', 'stop', 'status', 'remove', 'probe'):
        p = sub.add_parser(op)
        p.add_argument('profile', type=profile_name)
        if op == 'probe':
            p.add_argument('--ipv6', action='store_true')
    p = sub.add_parser('import')
    p.add_argument('profile', type=profile_name)
    p.add_argument('file', type=Path)
    p = sub.add_parser('run')
    p.add_argument('profile', type=profile_name)
    p.add_argument('command', nargs=argparse.REMAINDER)
    sub.add_parser('gui')
    args = parser.parse_args()
    try:
        if args.op == 'gui':
            from .gui import main as gui
            return gui()
        if args.op == 'run':
            argv = args.command
            if argv and argv[0] == '--':
                argv = argv[1:]
            if not argv:
                parser.error('run requires a command after --')
            return client.run(args.profile, argv)
        if args.op == 'probe':
            print(client.probe(args.profile, args.ipv6))
            return 0
        values = {} if args.op == 'list' else {'profile': args.profile}
        if args.op == 'import':
            with args.file.open() as source:
                text = source.read(MAX_CONFIG + 1)
            parse(text)
            values['config'] = text
        print(json.dumps(client.call(args.op, **values), indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f'appwire: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

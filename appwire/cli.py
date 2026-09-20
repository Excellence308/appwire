import argparse
import json
from pathlib import Path
import subprocess
import sys
from . import client, local, __version__
from .config import MAX_CONFIG, parse, profile_name


def read_config(path):
    with Path(path).open() as source:
        text = source.read(MAX_CONFIG + 1)
    parse(text)
    return text


def main():
    parser = argparse.ArgumentParser(description='AppWire: per-app WireGuard, without host routing changes')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='op', required=True)
    for op in ('list', 'doctor', 'setup', 'gui'):
        sub.add_parser(op)
    for op in ('start', 'stop', 'status', 'remove', 'probe'):
        p = sub.add_parser(op)
        p.add_argument('profile', type=profile_name)
        if op == 'probe':
            p.add_argument('--ipv6', action='store_true')
    p = sub.add_parser('rename')
    p.add_argument('profile', type=profile_name)
    p.add_argument('new_name', type=profile_name)
    p = sub.add_parser('import')
    p.add_argument('profile', type=profile_name)
    p.add_argument('file', type=Path)
    p.add_argument('--replace', action='store_true')
    p = sub.add_parser('import-many')
    p.add_argument('files', nargs='+', type=Path)
    p.add_argument('--replace', action='store_true')
    p = sub.add_parser('run')
    p.add_argument('--log', action='store_true', help='Write application output to bounded private logs')
    p.add_argument('profile', type=profile_name)
    p.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.op == 'gui':
            from .gui import main as gui
            return gui()
        if args.op == 'doctor':
            result = local.doctor()
        elif args.op == 'setup':
            print(local.setup())
            return 0
        elif args.op == 'run':
            argv = args.command[1:] if args.command[:1] == ['--'] else args.command
            if not argv:
                parser.error('run requires a command after --')
            return local.logged_launch(args.profile, argv) if args.log else client.run(args.profile, argv)
        elif args.op == 'probe':
            print(client.probe(args.profile, args.ipv6))
            return 0
        elif args.op == 'import-many':
            result = []
            for path in args.files:
                name = local.suggested_name(path)
                try:
                    result.append(client.call('import', profile=name, config=read_config(path), replace=args.replace))
                except (OSError, ValueError, RuntimeError) as error:
                    result.append({'profile': name, 'ok': False, 'error': str(error)})
            print(json.dumps(result, indent=2))
            return int(any(not item.get('ok') for item in result))
        else:
            values = {} if args.op == 'list' else {'profile': args.profile}
            if args.op == 'import':
                values.update(config=read_config(args.file), replace=args.replace)
            if args.op == 'rename':
                values['new_name'] = args.new_name
            result = client.call(args.op, **values)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'appwire: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

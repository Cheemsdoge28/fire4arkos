#!/usr/bin/env python3
from pathlib import Path
import argparse
import re
import sys

SYSTEM_BLOCK = '''  <system>
    <name>fire4arkos</name>
    <fullname>Fire4ArkOS Browser</fullname>
    <path>{install_dir}</path>
    <extension>.sh</extension>
    <command>bash %ROM%</command>
    <platform>{platform_tag}</platform>
    <theme>{theme_name}</theme>
  </system>
'''


def insert_system(filename, install_dir, platform_tag='fire4arkos', theme_name='fire4arkos'):
    filename = Path(filename)
    with open(filename, encoding='utf-8') as fh:
        ctx = fh.read()

    # Check if fire4arkos already exists and remove the old entry first
    if re.search(r'<name>fire4arkos</name>', ctx):
        print(f'fire4arkos already present in {filename} — removing old entry for update')
        # Remove the old system block: from <!-- Fire4ArkOS to </system>
        ctx = re.sub(r'\s*<!-- Fire4ArkOS.*?</system>', '', ctx, flags=re.DOTALL)
        # Also try to remove with just name check in case no comment exists
        ctx = re.sub(r'\s*<system>\s*<name>fire4arkos</name>.*?</system>', '', ctx, flags=re.DOTALL)

    system_block = SYSTEM_BLOCK.format(
        install_dir=install_dir,
        platform_tag=platform_tag,
        theme_name=theme_name,
    )

    if not re.search(r'</systemList>', ctx):
        raise RuntimeError(f'Failed to find </systemList> in {filename}')

    backup = filename.with_name(filename.name + '.bak.fire4arkos')
    filename.rename(backup)

    ctx = re.sub(r'</systemList>', system_block + r'\g<0>', ctx)

    with open(filename, 'w', encoding='utf-8') as fh:
        fh.write(ctx)

    print(f'Successfully modified {filename} (backup: {backup})')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Insert Fire4ArkOS into EmulationStation config')
    parser.add_argument('--cfg-file', dest='cfg_file', action='store', type=str, default='/etc/emulationstation/es_systems.cfg', help='cfg file to process')
    parser.add_argument('--install-dir', dest='install_dir', action='store', type=str, default='/roms/tools/fire4arkos', help='Install directory for the Fire4ArkOS package')
    parser.add_argument('--platform-tag', dest='platform_tag', action='store', type=str, default='fire4arkos', help='Platform tag to register')
    parser.add_argument('--theme-name', dest='theme_name', action='store', type=str, default='fire4arkos', help='Theme name to register')
    args = parser.parse_args()

    try:
        insert_system(
            args.cfg_file,
            install_dir=args.install_dir,
            platform_tag=args.platform_tag,
            theme_name=args.theme_name,
        )
    except Exception as exc:
        print(f'Failed to modify {args.cfg_file}: {exc}', file=sys.stderr)
        raise SystemExit(1)

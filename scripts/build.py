#!/usr/bin/env python3
"""Build the pinned offline Apple Silicon DMG. No personal runtime files copied."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / '.cache'
BUILD = ROOT / 'build.noindex'
DIST = ROOT / 'dist'
APP_NAME = 'DJOneHub.app'


def run(args):
    return subprocess.check_output([str(a) for a in args], text=True).strip()


def obtain(name, dependency):
    path = CACHE / name
    if not path.exists():
        urllib.request.urlretrieve(dependency['url'], path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != dependency['sha256']:
        raise RuntimeError('Dependency checksum mismatch: ' + name)
    return path


def copy_upstream(target):
    """Use a reviewed local upstream tree when DMG mounting is unavailable."""
    source = os.environ.get('DJONEHUB_UPSTREAM_DIR')
    if not source:
        return False
    upstream = Path(source).expanduser()
    if upstream.name != 'djonehub':
        upstream /= 'djonehub'
    if not (upstream / 'bin/djonehub-macos').is_file():
        raise RuntimeError('DJONEHUB_UPSTREAM_DIR does not contain djonehub/bin/djonehub-macos')
    shutil.copytree(upstream, target / 'djonehub', symlinks=True)
    return True


def main():
    version = (ROOT / 'VERSION').read_text().strip()
    dependencies = json.loads((ROOT / 'DEPENDENCIES.json').read_text())
    for directory in (CACHE, BUILD, DIST):
        directory.mkdir(exist_ok=True)
    archive = obtain('python-arm64.tar.gz', dependencies['python'])
    upstream_dmg = obtain('enhanced-v1.2.9.dmg', dependencies['djonehub_enhanced'])
    app = BUILD / APP_NAME
    if app.exists():
        shutil.rmtree(app)
    resources = app / 'Contents/Resources'
    macos = app / 'Contents/MacOS'
    resources.mkdir(parents=True)
    macos.mkdir()
    with tarfile.open(archive) as bundle:
        # Asset integrity was checked first; reject unexpected archive traversal.
        for member in bundle.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts:
                raise RuntimeError('Unsafe runtime archive entry')
        bundle.extractall(resources)
    for name in ('network_control.py', 'quota_control.py'):
        shutil.copy2(ROOT / 'src' / name, resources / name)
    shutil.copy2(ROOT / 'scripts/install_runtime.py', resources / 'install_runtime.py')
    shutil.copytree(ROOT / 'licenses', resources / 'licenses')
    shutil.copy2(ROOT / 'LICENSE', resources / 'LICENSE')
    shutil.copy2(ROOT / 'THIRD_PARTY_NOTICES.md', resources / 'THIRD_PARTY_NOTICES.md')
    shutil.copy2(ROOT / 'DEPENDENCIES.json', resources / 'DEPENDENCIES.json')
    target = resources / 'upstream'
    target.mkdir()
    if not copy_upstream(target):
        mounted = plistlib.loads(subprocess.check_output(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-plist', str(upstream_dmg)]))
        mount = next(Path(e['mount-point']) for e in mounted['system-entities'] if e.get('mount-point'))
        try:
            for name in ('djonehub',):
                shutil.copytree(mount / name, target / name, symlinks=True)
        finally:
            run(['/usr/bin/hdiutil', 'detach', mount])
    developer = Path('/Applications/Xcode.app/Contents/Developer')
    compiler = developer / 'Toolchains/XcodeDefault.xctoolchain/usr/bin/swiftc'
    sdk = developer / 'Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk'
    if not compiler.exists():
        compiler = Path(run(['/usr/bin/xcrun', '--find', 'swiftc']))
        sdk = Path(run(['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-path']))
    from integrate_native import prepare
    native = BUILD / 'native'
    if native.exists(): shutil.rmtree(native)
    prepare(ROOT, native)
    env = dict(__import__('os').environ, DEVELOPER_DIR=str(developer), SDKROOT=str(sdk),
               CLANG_MODULE_CACHE_PATH=str(CACHE / 'swift-module-cache'))
    swift = developer / 'Toolchains/XcodeDefault.xctoolchain/usr/bin/swift'
    subprocess.run([str(swift), 'build', '--package-path', str(native), '--disable-sandbox', '-c', 'release',
                    '-debug-info-format', 'none', '--triple', 'arm64-apple-macosx13.0', '--sdk', str(sdk)],
                   env=env, check=True)
    bin_directory = subprocess.check_output([str(swift), 'build', '--package-path', str(native), '-c', 'release',
                    '--triple', 'arm64-apple-macosx13.0', '--sdk', str(sdk), '--show-bin-path'], env=env, text=True).strip().splitlines()[-1]
    binary = Path(bin_directory) / 'DJOneHubNotifier'
    shutil.copy2(binary, macos / 'DJOneHub')
    shutil.copy2(native / 'Resources/AppIcon.icns', resources / 'AppIcon.icns')
    info = plistlib.loads((native / 'Info.plist').read_bytes())
    info.update(CFBundleName='DJOneHub', CFBundleDisplayName='DJOneHub', CFBundleExecutable='DJOneHub',
                CFBundleIdentifier='io.github.aeromelo.djonehub.mac', CFBundleShortVersionString=version,
                CFBundleVersion=str(int(''.join('%02d' % int(part) for part in version.split('.')))), LSMinimumSystemVersion='13.0')
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    # Sign executable Python modules/libraries before the enclosing bundle.
    for path in sorted((resources / 'python').rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if path.is_file() and not path.is_symlink():
            description = run(['/usr/bin/file', '-b', path])
            if 'Mach-O' in description:
                run(['/usr/bin/codesign', '--force', '--sign', '-', path])
    run(['/usr/bin/codesign', '--force', '--sign', '-', app])
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app])
    print(run([macos / 'DJOneHub', '--self-test']))
    stage = BUILD / 'dmg-root'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    shutil.copytree(app, stage / APP_NAME, symlinks=True)
    for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, stage / name)
    shutil.copytree(ROOT / 'docs', stage / 'docs')
    installer = stage / '安装或升级 DJOneHub.command'
    installer.write_text('#!/bin/zsh\nset -eu\nroot="${0:A:h}"\n/usr/bin/open -n "$root/DJOneHub.app" --args --install\n')
    installer.chmod(0o755)
    asset = DIST / ('DJOneHub-Mac-%s-macOS-arm64.dmg' % version)
    # A previous mounted release must be ejected by the builder before replacing it.
    images = plistlib.loads(subprocess.check_output(['/usr/bin/hdiutil', 'info', '-plist']))
    if any(i.get('image-path') == str(asset.resolve()) for i in images.get('images', [])):
        raise RuntimeError('Eject the previous release DMG before rebuilding')
    if asset.exists():
        asset.unlink()
    run(['/usr/bin/hdiutil', 'create', '-volname', 'DJOneHub ' + version,
         '-srcfolder', stage, '-ov', '-format', 'UDZO', asset])
    images = plistlib.loads(subprocess.check_output(['/usr/bin/hdiutil', 'info', '-plist']))
    for item in images.get('images', []):
        if item.get('image-path') == str(asset.resolve()) and item.get('writeable'):
            run(['/usr/bin/hdiutil', 'detach', item['system-entities'][0]['dev-entry']])
    (DIST / 'SHA256SUMS.txt').write_text(hashlib.sha256(asset.read_bytes()).hexdigest() + '  ' + asset.name + '\n')
    print('Created', asset)


if __name__ == '__main__':
    main()

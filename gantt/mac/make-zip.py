#!/usr/bin/env python3
"""gantt/index.html の最新版を Mac 用アプリに入れて、タスク管理-mac.zip を作り直す。
使い方: python3 gantt/mac/make-zip.py
"""
import os, shutil, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = 'タスク管理.app'
shutil.copyfile(os.path.join(HERE, '..', 'index.html'), os.path.join(HERE, APP, 'Contents', 'Resources', 'index.html'))

out = os.path.join(HERE, 'タスク管理-mac.zip')
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(os.path.join(HERE, APP)):
        dirs.sort()
        rel_root = os.path.relpath(root, HERE)
        zi = zipfile.ZipInfo(rel_root + '/')
        zi.external_attr = (0o40755 << 16) | 0x10
        zi.create_system = 3
        z.writestr(zi, '')
        for f in sorted(files):
            path = os.path.join(root, f)
            zi = zipfile.ZipInfo(os.path.join(rel_root, f))
            zi.external_attr = ((0o100755 if os.access(path, os.X_OK) else 0o100644) << 16)
            zi.create_system = 3  # Unix: 実行権限を保持
            zi.compress_type = zipfile.ZIP_DEFLATED
            with open(path, 'rb') as fh:
                z.writestr(zi, fh.read())
print('作成しました:', out)

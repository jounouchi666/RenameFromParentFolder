import sys
import os

# コマンドライン引数からファイルパスを取得
file_paths = sys.argv[1:]

# ファイルパスが指定されていない場合はエラー
if not file_paths:
    print("エラー： ファイルパスが指定されていません")
    sys.exit(1)

# 親フォルダを取得
parent_folder = os.path.dirname(file_paths[0])
parent_folder_name = os.path.basename(parent_folder)

# 名前順にソート
file_paths.sort()

# 選択したファイルが 1 つなら連番なし、複数なら連番を付ける
if len(file_paths) == 1:
    ext = os.path.splitext(file_paths[0])[1]  # 拡張子を保持
    new_filename = f"{parent_folder_name}{ext}"
    new_path = os.path.join(parent_folder, new_filename)
    os.rename(file_paths[0], new_path)
else:
    for index, file_path in enumerate(file_paths, start=1):
        ext = os.path.splitext(file_path)[1]  # 拡張子を保持
        new_filename = f"{parent_folder_name}_{index:02d}{ext}"
        new_path = os.path.join(parent_folder, new_filename)
        os.rename(file_path, new_path)

print("ファイル名を変更しました。")
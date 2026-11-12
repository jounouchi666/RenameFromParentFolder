import argparse
import json
import os
import re
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile


TEMPLATE_PRESETS = {
    "underscore": "%parent%_$num(%track%,2)",
    "hyphen": "%parent%-$num(%track%,2)",
    "parentheses": "%parent% ($num(%track%,2))",
    "unpadded": "%parent%_%track%",
    "three_digits": "%parent%_$num(%track%,3)",
}
DEFAULT_TEMPLATE = TEMPLATE_PRESETS["underscore"]
SETTINGS_PATH = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "RenameFromParentFolder" / "settings.json"
TEMPLATE_TOKEN = re.compile(r"\$num\(\s*%track%\s*,\s*([0-9]{1,2})\s*\)|%[^%]*%|\$num\b|%")
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_FILENAME = re.compile(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³])", re.IGNORECASE)


def load_template() -> str:
    try:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_TEMPLATE

    if isinstance(settings, dict):
        template = settings.get("template")
        if isinstance(template, str):
            return template
        legacy_format = settings.get("number_format")
        if isinstance(legacy_format, str) and legacy_format in TEMPLATE_PRESETS:
            return TEMPLATE_PRESETS[legacy_format]
    raise ValueError("ファイル名の書式を読み込めません。")


def render_filename(template: str, source: Path, index: int) -> str:
    title, extension = os.path.splitext(source.name)
    fields = {"%parent%": source.parent.name, "%title%": title, "%track%": str(index), "%%": "%"}

    def replace(match: re.Match[str]) -> str:
        if match[1] is not None:
            width = int(match[1])
            if not 1 <= width <= 9:
                raise ValueError("$num の桁数は 1〜9 を指定してください。")
            return str(index).zfill(width)
        token = match[0]
        if token not in fields:
            raise ValueError(f"書式を確認してください（{token}）。")
        return fields[token]

    stem = TEMPLATE_TOKEN.sub(replace, template)
    filename = stem + extension
    device_name = filename.partition(".")[0].rstrip(" ")
    if (
        not stem.strip()
        or stem in {".", ".."}
        or INVALID_FILENAME.search(filename)
        or RESERVED_FILENAME.fullmatch(device_name)
        or filename.endswith((" ", "."))
        or len(filename.encode("utf-16-le")) > 510
    ):
        raise ValueError(f"Windows で使えないファイル名です（{filename}）。")
    return filename


def show_settings() -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    window = tk.Tk()
    window.title("親フォルダの名前に変更の設定")
    window.minsize(480, 0)
    window.resizable(True, False)
    try:
        initial = load_template()
    except (OSError, ValueError):
        initial = DEFAULT_TEMPLATE
    template = tk.StringVar(window, initial)
    preview = tk.StringVar(window)

    def save() -> None:
        if not update_preview():
            return
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=SETTINGS_PATH.parent, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    json.dump({"template": template.get()}, stream, ensure_ascii=False)
                    stream.close()
                    temporary.replace(SETTINGS_PATH)
                finally:
                    temporary.unlink(missing_ok=True)
        except OSError as error:
            messagebox.showerror("設定を保存できません", str(error), parent=window)
        else:
            window.destroy()

    def update_preview(*_args: str) -> bool:
        try:
            examples = (
                render_filename(template.get(), Path("親フォルダ") / "元ファイルA.jpg", 1),
                render_filename(template.get(), Path("親フォルダ") / "元ファイルB.jpg", 2),
            )
            if examples[0].casefold() == examples[1].casefold():
                raise ValueError("例の変更先が重複します。%track% などを使ってください。")
        except ValueError as error:
            preview.set(str(error))
            save_button.state(["disabled"])
            return False
        preview.set("\n".join(examples))
        save_button.state(["!disabled"])
        return True

    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="複数ファイルのファイル名書式").pack(anchor="w", pady=(0, 4))
    entry = ttk.Combobox(frame, textvariable=template, values=list(TEMPLATE_PRESETS.values()))
    entry.pack(fill="x")
    ttk.Label(
        frame,
        text="%parent% 親フォルダ名　%title% 元のファイル名　%track% 連番\n"
        "$num(%track%,2) 2桁の連番　%% パーセント記号\n"
        "拡張子は元のファイルから引き継ぎます。",
    ).pack(anchor="w", pady=(8, 12))
    ttk.Label(frame, text="プレビュー").pack(anchor="w")
    ttk.Label(frame, textvariable=preview, wraplength=440).pack(anchor="w", pady=(4, 0))
    buttons = ttk.Frame(frame)
    buttons.pack(anchor="e", pady=(16, 0))
    ttk.Button(buttons, text="キャンセル", command=window.destroy).pack(side="left", padx=(0, 8))
    save_button = ttk.Button(buttons, text="保存", command=save)
    save_button.pack(side="left")
    template.trace_add("write", update_preview)
    update_preview()
    entry.focus_set()
    entry.selection_range(0, "end")
    window.bind("<Escape>", lambda event: window.destroy())
    window.mainloop()


def plan_renames(file_paths: list[Path], template: str = DEFAULT_TEMPLATE) -> list[tuple[Path, Path]]:
    sources = sorted((Path(os.path.abspath(path)) for path in file_paths), key=str)
    if len(set(sources)) != len(sources):
        raise ValueError("同じファイルが複数回指定されています。")

    parent = sources[0].parent
    if any(source.parent != parent for source in sources):
        raise ValueError("同じフォルダ内のファイルを指定してください。")
    if not parent.name:
        raise ValueError("ドライブのルートにあるファイルは対象外です。")

    renames = []
    targets = set()
    for index, source in enumerate(sources, start=1):
        if not source.is_file():
            raise ValueError(f"ファイルを確認できません: {source}")

        filename = render_filename(template if len(sources) > 1 else "%parent%", source, index)
        target = source.with_name(filename)
        if target in targets:
            raise ValueError(f"変更先のファイル名が重複しています（{target.name}）。")
        targets.add(target)
        if source.name == target.name:
            continue
        if source != target and os.path.lexists(target):
            raise FileExistsError(f"変更先が既に存在します: {target}")
        renames.append((source, target))

    return renames


def main() -> int:
    parser = argparse.ArgumentParser(description="ファイル名を親フォルダの名前に変更します。")
    parser.add_argument("--dry-run", action="store_true", help="変更予定を表示します。")
    parser.add_argument("--settings", action="store_true", help="連番形式の設定を開きます。")
    parser.add_argument("--explorer", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--selection-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("files", nargs="*", type=Path, metavar="ファイル")
    args = parser.parse_args()

    try:
        if args.settings:
            show_settings()
            return 0

        files = args.files
        if args.selection_file:
            try:
                files = [Path(line) for line in args.selection_file.read_text(encoding="utf-8").split("\n") if line]
            finally:
                args.selection_file.unlink(missing_ok=True)
        if not files:
            parser.error("ファイルを指定してください。")

        template = load_template() if len(files) > 1 else DEFAULT_TEMPLATE
        renames = plan_renames(files, template)
        if not renames:
            print("変更対象はありません。")
            return 0

        for source, target in renames:
            if not args.dry_run:
                source.rename(target)
            print(f"{source.name} → {target.name}")
    except (OSError, ValueError) as error:
        if args.explorer:
            from ctypes import windll

            windll.user32.MessageBoxW(None, str(error), "親フォルダ名に変更", 0x10)
        else:
            print(f"エラー: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

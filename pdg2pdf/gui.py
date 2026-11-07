from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from .converter import convert_book


class ConverterWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="PDG 转 PDF")
        self.set_default_size(700, 360)
        self.set_border_width(18)
        self.set_resizable(True)
        self._busy = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(root)

        heading = Gtk.Label()
        heading.set_markup("<big><b>PDG 转 PDF</b></big>\n支持目录、ZIP、伪 PDG、HH 容器和早期加密 PDG")
        heading.set_xalign(0)
        root.pack_start(heading, False, False, 0)

        source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        source_label = Gtk.Label(label="输入目录或 ZIP")
        source_label.set_xalign(0)
        self.source_entry = Gtk.Entry()
        self.source_entry.set_hexpand(True)
        folder_button = Gtk.Button(label="选目录")
        folder_button.connect("clicked", self._choose_source_folder)
        zip_button = Gtk.Button(label="选 ZIP")
        zip_button.connect("clicked", self._choose_source_zip)
        source_row.pack_start(source_label, False, False, 0)
        source_row.pack_start(self.source_entry, True, True, 0)
        source_row.pack_start(folder_button, False, False, 0)
        source_row.pack_start(zip_button, False, False, 0)
        root.pack_start(source_row, False, False, 0)
        output_row, self.output_entry = self._path_row("输出 PDF", self._choose_output)
        root.pack_start(output_row, False, False, 0)

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_label = Gtk.Label(label="PDF 标题")
        title_label.set_xalign(0)
        self.title_entry = Gtk.Entry()
        self.title_entry.set_hexpand(True)
        title_row.pack_start(title_label, False, False, 0)
        title_row.pack_start(self.title_entry, True, True, 0)
        root.pack_start(title_row, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        root.pack_start(self.progress, False, False, 0)

        self.status = Gtk.Label(label="请选择输入目录或 ZIP 文件")
        self.status.set_xalign(0)
        self.status.set_line_wrap(True)
        root.pack_start(self.status, False, False, 0)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.convert_button = Gtk.Button(label="开始转换")
        self.convert_button.connect("clicked", self._start_conversion)
        close_button = Gtk.Button(label="关闭")
        close_button.connect("clicked", self._on_close_clicked)
        button_row.pack_end(close_button, False, False, 0)
        button_row.pack_end(self.convert_button, False, False, 0)
        root.pack_end(button_row, False, False, 0)

        self.connect("destroy", self._on_destroy)

    def _on_close_clicked(self, _button) -> None:
        self.destroy()

    def _on_destroy(self, _window) -> None:
        if Gtk.main_level() > 0:
            Gtk.main_quit()

    def _path_row(self, label: str, callback):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        text = Gtk.Label(label=label)
        text.set_xalign(0)
        entry = Gtk.Entry()
        entry.set_hexpand(True)
        button = Gtk.Button(label="选择")
        button.connect("clicked", callback, entry)
        row.pack_start(text, False, False, 0)
        row.pack_start(entry, True, True, 0)
        row.pack_start(button, False, False, 0)
        return row, entry

    def _choose_source_folder(self, _button) -> None:
        dialog = Gtk.FileChooserDialog(
            title="选择输入目录",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            buttons=("取消", Gtk.ResponseType.CANCEL, "选择", Gtk.ResponseType.OK),
        )
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self._set_source(dialog.get_filename() or "")
        dialog.destroy()

    def _choose_source_zip(self, _button) -> None:
        dialog = Gtk.FileChooserDialog(
            title="选择输入 ZIP",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
            buttons=("取消", Gtk.ResponseType.CANCEL, "选择", Gtk.ResponseType.OK),
        )
        filter_zip = Gtk.FileFilter()
        filter_zip.set_name("ZIP archive")
        filter_zip.add_pattern("*.zip")
        dialog.add_filter(filter_zip)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self._set_source(dialog.get_filename() or "")
        dialog.destroy()

    def _set_source(self, filename: str) -> None:
        self.source_entry.set_text(filename)
        if not self.output_entry.get_text():
            self.output_entry.set_text(str(Path(filename).with_suffix(".pdf")))

    def _choose_output(self, _button, entry: Gtk.Entry) -> None:
        dialog = Gtk.FileChooserDialog(
            title="选择输出 PDF",
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
            buttons=("取消", Gtk.ResponseType.CANCEL, "保存", Gtk.ResponseType.OK),
        )
        dialog.set_do_overwrite_confirmation(True)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename() or ""
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            entry.set_text(filename)
        dialog.destroy()

    def _start_conversion(self, _button) -> None:
        if self._busy:
            return
        source = self.source_entry.get_text().strip()
        output = self.output_entry.get_text().strip()
        if not source or not output:
            self.status.set_text("请先选择输入和输出路径")
            return
        self._busy = True
        self.convert_button.set_sensitive(False)
        self.progress.set_fraction(0)
        self.progress.set_text("准备中")
        thread = threading.Thread(target=self._convert_worker, args=(source, output, self.title_entry.get_text().strip()), daemon=True)
        thread.start()

    def _convert_worker(self, source: str, output: str, title: str) -> None:
        try:
            result = convert_book(
                source,
                output,
                title=title or None,
                progress=lambda done, total, name: GLib.idle_add(self._progress, done, total, name),
            )
            GLib.idle_add(self._finished, f"转换完成：{result.output}，共 {result.page_count} 页")
        except Exception as exc:
            GLib.idle_add(self._finished, f"转换失败：{exc}")

    def _progress(self, done: int, total: int, name: str) -> bool:
        self.progress.set_fraction(done / max(total, 1))
        self.progress.set_text(f"{done}/{total}  {name}")
        self.status.set_text(f"正在处理：{name}")
        return False

    def _finished(self, message: str) -> bool:
        self._busy = False
        self.convert_button.set_sensitive(True)
        self.status.set_text(message)
        if message.startswith("转换完成"):
            self.progress.set_fraction(1)
            self.progress.set_text("完成")
        else:
            self.progress.set_text("失败")
        return False


def run_gui() -> int:
    window = ConverterWindow()
    window.show_all()
    Gtk.main()
    return 0

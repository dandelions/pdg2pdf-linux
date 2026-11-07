# pdg2pdf

Linux 原生 PDG 转 PDF 工具，提供命令行和 GTK3 图形界面。转换核心为纯 Python，不依赖 Wine。

## 支持格式

- 伪 PDG：文件内容实际为 JPEG、PNG、BMP、TIFF 或 GIF，只是扩展名为 `.pdg`
- 标准 HH 容器 PDG：包括 JPEG、PNG、BMP、DjVu 等页面载荷
- 早期历史版本加密 PDG：Type 1-5、11-1C、A0-AF
- 输入目录或 ZIP 书包
- `bookinfo.dat` / `bookInfo.txt` 标题和作者
- `BookContents.dat` 目录书签

对于 DjVu 页面，需要安装 DjVuLibre：

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 djvulibre-bin
python3 -m pip install --user img2pdf pikepdf Pillow pytest
```

## 命令行

```bash
python3 pdg2pdf.py input-book output.pdf
python3 pdg2pdf.py input-book.zip output.pdf --title "自定义标题"
```

`input-book` 可以是包含 PDG 页面的目录，输出路径省略时默认为同名 `.pdf`。

## 图形界面

```bash
python3 pdg2pdf.py --gui
```

也可以直接运行：

```bash
python3 -m pdg2pdf.cli --gui
```

图形界面支持选择输入目录或 ZIP、选择输出文件、设置标题、进度显示和后台转换。

## 已知限制

- Type FF 和 6x 等 DRM 绑定格式不属于早期普通加密格式，当前不承诺支持。
- 目录页码依赖来源书包的 `BookContents.dat` 编码；缺失或损坏时仍会生成 PDF，但不生成书签。

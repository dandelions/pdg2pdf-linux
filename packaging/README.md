# Debian 安装包

项目提供两个 Debian 打包方式。

## 直接构建 `.deb`

只需要 `dpkg-deb`：

```bash
./packaging/build-deb.sh
```

输出文件位于项目上一级目录，例如：

```text
../pdg2pdf-linux_1.0.2_amd64.deb
```

安装：

```bash
sudo apt install ../pdg2pdf-linux_1.0.2_amd64.deb
```

安装过程会自动安装这些运行依赖：

- Python 3.10 或更高版本
- GTK3 和 `python3-gi`
- DjVuLibre

Pillow、img2pdf、pikepdf 及其 Python 依赖会随 `.deb` 安装到应用自己的私有目录，不需要系统单独安装。包内为 Python 3.10、3.11、3.12、3.13 分别准备了一套私有依赖，启动时按系统 `python3` 的实际版本自动选择；如果系统 Python 版本不在此范围内，会提示并回退到系统安装的对应模块。

安装完成后：

```bash
pdg2pdf-gui
```

也可以从应用菜单打开 **PDG 转 PDF**，或使用命令行：

```bash
pdg2pdf /path/to/book /path/to/output.pdf
```

## 使用 Debian 标准工具构建

如果系统安装了 `debhelper-compat`，也可以执行：

```bash
dpkg-buildpackage -us -uc -b
```

生成的 `.deb` 文件在项目上一级目录。

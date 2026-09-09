<p align="center"><img src="scrollferry/assets/logo.png" width="120" alt="ScrollFerry Logo"></p>

# ScrollFerry · 舷渡

**小鹅通题库上传工具 · v1.0.2**

ScrollFerry 是一个 Python 桌面工具，将 PDF 试卷拆分为题干、选项、答案和解析截图，再通过浏览器批量录入小鹅通题库。它面向需要保留数学公式、图表和原有排版的试卷，减少逐题截图、上传素材和插图的重复操作。

软件使用原 PDF 的渲染结果，不改写源文件。自动拆题后可以手动校对，规则识别不能保证任意版式均正确。

## 文档导航

- [使用说明](docs/user-guide.md)：安装启动、截图校对、导出、上传和故障处理。
- [技术说明](docs/technical-guide.md)：模块结构、数据格式、上传状态及开发维护。
- [Windows 打包说明](docs/windows-packaging.md)：通过 GitHub Actions 生成安装 EXE。
- [集成验证记录](docs/xiaoe-integration.md)：历史实测过程，当前行为以代码和使用说明为准。

## 主要功能

- 自动识别带文字层 PDF 的题目和答案标记，分别截取题干、选项及解析。
- 保留公式和图片，遮盖原题号与选项标号，保留“解析”文字。
- 支持调整截图、擦除标号、追加跨页片段、撤销和重做。
- 支持 A–H 连续选项，包括五选项题；同行选项可分别切图。
- 每次导出新建批次，图片名称包含试卷名和批次编号。
- 先将整卷图片集中上传到专属素材分组，再创建或复用同名题库分类。
- 按导出清单倒序录题，按完整图片名搜索、插入并保存。
- 保留上传进度，恢复时跳过已保存题目；结果不确定时暂停核对。

| 本地题型 | 小鹅通题型 | 答案处理 |
| --- | --- | --- |
| 单选题 | 单选题 | 根据答案字母设置正确选项 |
| 多选题 | 多选题 | 根据多个答案字母设置正确选项 |
| 填空题 | 问答题 | 优先使用答案原图，其次已有文字答案 |
| 解答题 | 问答题 | 依次优先使用答案原图、文字答案、完整解析图 |

## 快速开始

### Windows 安装版

在仓库 Actions 中选择一次成功的 **Build Windows installer** 运行，下载附件 `ScrollFerry-Windows-Installer-1.0.2`。解压后运行 `ScrollFerry-Setup-1.0.2-x64.exe`。安装版包含 Python 和上传组件，电脑仍需安装 Chrome 或 Edge。

只有成功完成构建和安装检查的运行才提供附件；本文不代表已发布正式 Release，详见 [打包说明](docs/windows-packaging.md)。

### 源码运行

准备包含 Tcl/Tk 的 Python 3.11 或更新版本，推荐开发环境为 Python 3.12。

- macOS：双击 `start_mac.command`；需要上传时运行 `安装上传组件_mac.command`。
- Windows：双击 `start_windows.bat`；需要上传时运行 `安装上传组件_windows.bat`。

也可以在自己的虚拟环境中执行：

```bash
python -m pip install -r requirements.txt -r requirements-upload.txt
python -m scrollferry.app
```

上传使用软件独立的浏览器窗口，首次需要登录小鹅通。Windows 优先尝试默认的 Chrome 或 Edge，启动失败后尝试另一个；其他默认浏览器暂不支持直接接入。

## 一次完整操作

1. 点击“打开 PDF”，等待自动分析。
2. 校对题目数量、截图范围、选项和答案，必要时调整并保存工程。
3. 点击“导出截图”选择保存位置，软件自动建立批次子文件夹。
4. 点击“小鹅通上传”，先用“试传下一题”检查录入效果。它仍会先上传整卷素材，并真实保存一题。
5. 确认后选择“上传全部可用题目”，完成倒序录入。

上传期间保持软件及其专用浏览器窗口打开。重启后选择原批次的 `manifest.json` 可恢复上传。

## 数据存放

| 数据 | 保存位置 |
| --- | --- |
| 原 PDF、工程、导出截图 | 用户选择的位置 |
| Windows 登录资料、上传进度 | `%LOCALAPPDATA%\ScrollFerry` |
| macOS 登录资料、上传进度 | `~/Library/Application Support/ScrollFerry` |

恢复进度依赖原批次路径和本机用户数据，请保持目录位置不变。登录资料、实际试卷和运行输出不应上传到 GitHub。

## 当前边界

- 优先支持带文字层的单栏试卷；双栏、复杂表格、集中答案表和不规则编号可能需要调整或适配。
- 尚未接入扫描件 OCR，纯扫描件可能无法自动建立工程。
- 不提供 Word 转 PDF、钉钉验证或独立账号系统。
- 原 PDF 中已损坏或显示异常的公式不会自动修复。
- 小鹅通使用页面自动化，后台改版可能需要更新适配代码。
- 新规则不自动重建历史题目，也不重排已经保存的题目。

项目曾用一份 14 页、22 题试卷完成拆分及录题验证，并用生成 PDF 覆盖五选项和同行选项测试；这不代表所有版式、系统和题型组合均已验收。

## 开发与测试

```bash
python -m pip install -r requirements.txt -r requirements-upload.txt reportlab
python -m unittest discover -s tests -v
```

实际试卷回归需设置 `SCROLLFERRY_TEST_PDF` 指向本地样本，否则该项跳过。普通单元测试不登录小鹅通、不创建真实题目。Windows 安装包通过 GitHub 的 Windows runner 构建，具体架构和维护方式见 [技术说明](docs/technical-guide.md)。

# 开发与构建

| 路径 | 内容 |
|---|---|
| e7_assistant/ | ADB、识别、规则、主流程与WebView桥接 |
| frontend/src/ | React桌面界面 |
| e7_assistant/assets/ | 识别模板、品牌图像、编译后的前端 |
| tests/ | 离线回归，部分依赖本地历史图像 |
| scripts/ | 构建、验收与开发期诊断 |
| examples/ | 构造或人工标注示例，不等同OCR实测 |

部分scripts实机排错脚本绑定开发时的设备、页面与旧任务。它们不是公众任务入口；先阅读代码，勿直接执行含消费动作的脚本。

## 前端

安装Node.js 22.12+和npm：

```powershell
cd frontend
npm ci
npm run build
cd ..
```

Vite输出到e7_assistant/assets/web。浏览器开发服务器没有Python桌面桥接，游戏任务用客户端.py启动。

## 可移植的离线检查

```powershell
$env:PYTHONPATH = Join-Path $PWD 'tests'
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_rules tests.test_settings tests.test_custom_targets tests.test_client_entry tests.test_desktop_api tests.test_desktop_task_dispatch
```

全量unittest discover部分用例引用未公开的captures、runs和历史截图，缺少样本可能失败。不能把跳过或旧报告视为新版本通过。

## Windows EXE

先按首页安装Python依赖、执行npm ci，关闭正在使用的助手，再构建：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -X utf8 scripts/build_windows_client.py
```

构建会编译前端并收集OCR依赖，输出dist/第七史诗打铁助手.exe。MuMu、ADB和WebView2仍需另行提供。不要覆盖运行中的EXE。

scripts/verify_windows_client.py检查独立运行时、WebView与历史截图；它依赖本地captures/trial-plus9-after.png，公开仓库未附该样本。UI检查前关闭现有助手，避免单实例冲突。实机验收会实际操作游戏，应明确设备和预算。

## 提交约定

改强化、保留、上锁或淘汰规则须同步enhancement-rules.md对应章节与版本记录。报告区分离线、EXE和实机验证。不要上传个人配置、账号截图、日志、ADB工具包、虚拟环境、构建缓存与快捷方式。

当前未指定源码许可证，再分发授权请与维护者确认；第三方依赖和游戏图像仍受各自许可与权利约束。

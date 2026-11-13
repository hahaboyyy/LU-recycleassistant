**LU Recycle Assistant · 小组复现说明**

这是垃圾分类助手的整合版本，面向岭南大学场景，覆盖 16 种物品，每张照片处理一个主要物体。英文页面支持上传、拍照、最多两轮追问、人工纠正、规则建议和判断依据展示。识别使用现成视觉模型 API，物品确认后返回 A 规则库的对应建议。

**Windows 首次安装**

使用 Python 3.11，在本仓库根目录打开 PowerShell。通过 GitHub 克隆仓库或下载 ZIP 后，先进入含 app.py 的文件夹，再执行以下命令。

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
```

requirements-lock.txt 固定了本次复现验证使用的依赖版本，包含 pytest。日常只安装应用依赖时可使用 requirements.txt，需要测试则使用 requirements-dev.txt。

**启动真实识别**

用编辑器打开刚复制的 .env，在 RECO_API_KEY 后填写小组分配给你的可用密钥。模板保留了本次成功调用使用的端点和模型 ID，若小组换了服务，请同时更新 RECO_BASE_URL 和 RECO_MODEL。

```powershell
.\Start-Demo.ps1 -Live -Port 8502
```

打开 [本机真实识别页面](http://127.0.0.1:8502)。选择 Camera 现拍，或上传一张照片，再点 Identify item。真实模式会把规范化后的图片发送给配置的视觉 API。密钥权限、模型权限和网络连接需要有效。

追问和人工纠正复用已有识别记录，并查询本地规则。支持物品确认后显示 Identification 和 Disposal Advice，可展开 Why this advice? 查看确认来源和目的地。鼠标等超范围物品会得到相应提示。

**体验离线流程**

```powershell
.\Start-Demo.ps1
```

打开 [本机离线演示页面](http://127.0.0.1:8501)。这一模式根据所选开发案例生成预设识别响应，随后执行实际的判断和页面流程。

| 案例 | 可以尝试的操作 |
|---|---|
| DEV-01 | 查看塑料瓶建议，再点 Wrong item? 改为玻璃瓶。 |
| DEV-17 | 回答 Glass，查看建议。 |
| TWO_QUESTIONS | 连续选 Not sure，查看两轮后无法确认的提示。 |
| DEV-19 / UNCLEAR | 查看超范围和补拍提示。 |
| ERROR / TIMEOUT | 查看接口失败、超时和重试状态。 |

**macOS / Linux 运行**

同样使用 Python 3.11，在仓库根目录执行。

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
cp .env.example .env
# Edit .env and set RECO_API_KEY before using live mode.
export PYTHONPATH="$PWD/recognition/src"
export RECO_ENV_FILE="$PWD/.env"
export RECYCLE_D_BACKEND="integration:create_live_backend"
.venv/bin/python -m streamlit run app.py --server.port 8502
```

离线模式启动前执行 unset RECYCLE_D_BACKEND，再运行 Streamlit。Windows 是本次实际复现验证的平台。

**验证代码与数据**

```powershell
New-Item -ItemType Directory -Force -Path .pytest_cache | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest_cache/tmp
.\.venv\Scripts\python.exe -m unittest -q test_backend
```

当前基线为 160 项 pytest 和 11 项 unittest。测试涵盖识别契约、16 个规则条目、开发流程、C 的回答回归、追问上限与页面状态。60 条 E 预设观察的回放验证判断流程。真实 API 曾通过塑料瓶和纸巾开发照片的联调，最终版本的正式视觉评估另行记录。

2026-11-13 在独立 Git 克隆和全新 Python 3.11 虚拟环境中，按 requirements-lock.txt 安装后，上述 160 项和 11 项检查均通过。

测试命令可在无密钥状态下运行。测试生成的缓存和日志位于本仓库的 .pytest_cache/ 和 runs/。

**文件用途**

| 文件或目录 | 作用 |
|---|---|
| app.py、assets/、.streamlit/ | D 的英文界面、卡通素材、CSS 和本机运行主题。 |
| backend.py、integration.py、decision.py | F 的接口、识别调用与 C 的历史适配。 |
| module_c.py | C 的会话判断与规则查询，包含 F 的集成修正。 |
| recognition/ | B 的识别、基线、输出结构和模块测试。 |
| data/ | A 的规则、支持物品、20 张开发图及出处。 |
| evaluation/ | E 的 60 张测试图、参考答案、出处和评估工具。 |
| tests/、test_backend.py | 整合回归与 D 后端检查。 |
| docs/CONTRIBUTIONS.md | 成员贡献、集成修正和验证范围。 |
| ASSET_CREDITS.md | 开发照片署名，正式测试图的出处另见 evaluation/data/photo_provenance.csv。 |

E 的原始清单保留随交付提供的审核元数据。正式运行其评估命令前，按小组最终确认的清单和签核记录完成预检，再运行 evaluation_adapter:predict。请将真实视觉结果与预设观察回放分别标注。

**向组员分享**

每位成员克隆仓库后安装依赖，并在自己的 .env 中配置 API 密钥即可运行。更新代码时使用 git pull。私有仓库需要由仓库所有者授予成员访问权限。

代码的组内修改和成果归属由小组共同约定。照片使用随表记录的许可，复用时保留来源、作者和许可信息。

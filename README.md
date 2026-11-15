**LU Recycle Assistant · 小组复现说明**

这是垃圾分类助手的整合版本，面向岭南大学场景，覆盖 16 种物品，每张照片处理一个主要物体。英文页面支持上传、拍照、最多两轮追问、人工纠正、规则建议和判断依据展示。识别使用现成视觉模型 API，物品确认后返回 A 规则库的对应建议。

**Windows 首次安装**

使用 Python 3.11，在本仓库根目录打开 PowerShell。通过 GitHub 克隆仓库或下载 ZIP 后，先进入含 app.py 的文件夹，再执行以下命令。

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
# Keep the included .env for the temporary live demo.
```

requirements-lock.txt 固定了本次复现验证使用的依赖版本，包含 pytest。日常只安装应用依赖时可使用 requirements.txt，需要测试则使用 requirements-dev.txt。

**启动真实识别**

本次临时演示版已按项目所有者的明确授权包含 .env 和共享 API key，安装依赖后即可启动真实识别，无需另外填写密钥。请保留现有 .env，避免用空模板覆盖。演示结束后，项目所有者将在 API 服务商后台撤销共享 key；撤销后需要提供新的可用密钥。固定配置和校验方法见 [FREEZE.md](FREEZE.md)。

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
# Keep the included .env for the temporary live demo.
# The included .env contains the temporary live-demo configuration.
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

当前基线为 177 项 pytest 和 11 项 unittest。测试涵盖识别契约、16 个规则条目、开发流程、C 的回答回归、追问上限与页面状态。60 条 E 预设观察的回放验证判断流程。真实 API 曾通过塑料瓶和纸巾开发照片的联调，最终版本的正式视觉评估另行记录。

2026-11-13 在独立 Git 克隆和全新 Python 3.11 虚拟环境中，按 requirements-lock.txt 安装后，上述 160 项和 11 项检查均通过。

2026-11-14 修复了名称匹配覆盖不确定候选的问题：物品 ID 无法确认但存在有效候选时，保留歧义并进入追问。新增 6 项回归测试，包括用户分别确认塑料瓶和玻璃瓶的整合流程；本地复跑 166 项 pytest 和 11 项 unittest 均通过。

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


## Repair release 15 November 2026

# Repair evaluation 15 November 2026

The measured release uses 4096 output tokens, one bounded transient retry, and at most one additional visual identity check for eligible uncertain categories. A length-limited reply is reported as OUTPUT_LIMIT. Explicit supported-item corrections can replace a mistaken candidate. Demo explanations identify scripted responses accurately.

177 pytest checks and 11 backend checks passed locally. These are software checks, not image accuracy.

| Metric | Result | 90% threshold |
|---|---:|---|
| Usable initial recognition responses | 60/60 (100%) | Met |
| Photo-only exact IDs on clear supported images | 42/48 (87.5%) | Not met |
| Secondary reference-informed simulated users, clear IDs | 47/48 (97.9%) | Met under this assisted simulation |

The original three-arm primary comparison remains unchanged. Clear-item complete advice was 8/48 for the direct baseline and 42/48 for both integrated primary arms. Correct workflow action over all cases was 48/60, 51/60 and 53/60. A workflow action is not an item-identification score.

The secondary simulation adds reference-name answers to five questions that lack an original E fixture. It is not photo-only accuracy, a real-user study or an independent held-out test. The same images have been used to analyse repairs. No labels or images were changed, and no failed row was silently replaced.

Original run: formal60_2026-11-14. First repair: 58/60 usable, 43/48 clear IDs. Second repair: 60/60 usable, 42/48 clear IDs. All remain archived locally. Release raw responses contain 126 HTTP requests, including six identity-review requests; primary interactive rows reuse the initial observation.

See summary.csv, per_case.csv, acceptance_results.json, assistance_summary.json and reference_assisted_replay.jsonl. Semantic advice ratings are assistant assessments with explicit reasons and still require the team's review. Source snapshots and image hashes are retained.

The public Render service has not been reconfigured or re-accepted by this local experiment. See DEPLOYMENT.md for the live environment and validation steps. The backup recording and physical presentation-device check remain team tasks.

Details: [experiment records](docs/experiments/2026-11-15/RELEASE_NOTES.md), [report](docs/Final_Report_EN.md), and [deployment](DEPLOYMENT.md).

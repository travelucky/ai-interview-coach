# AI 模拟面试系统

这是现有参赛项目的 MVP 开发版本。当前保留 Flask、SQLAlchemy、SQLite 和原生前端结构，优先保证新环境可复现启动以及文字面试主流程可用。

当前版本：`0.3.0`。Bootstrap 与 Chart.js 已随源码提供，完成安装后断网也不会影响页面样式、图表和本地规则面试。

## 最快启动方式（Windows）

首次运行，在项目根目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\scripts\start.ps1
```

以后可直接双击 `start.bat`，或执行 `.\scripts\start.ps1`。脚本会检查数据库结构、启动服务，并打开 <http://127.0.0.1:5001>。在 VS Code 中也可按 `F5`，选择“运行 AI 模拟面试 MVP”。

## 环境要求

- Windows 10/11
- Python 3.11 或 3.12
- PowerShell 5.1 或更高版本

## 1. 创建运行环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2. 配置环境变量

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少设置一个随机的 `FLASK_SECRET_KEY`。大模型、Embedding 和讯飞配置均为可选项；不配置时仍可运行文字面试，并使用本地规则与 FTS5 完成检索和基础报告。

配置 Embedding 后，用管理员账号进入“知识库管理”并点击“刷新向量”，或执行评测命令验证效果：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py --mode lexical
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py --mode hybrid
```

混合检索失败会自动回退，不会阻断面试。知识文档可从后台按岗位导入 Markdown、TXT 或含可提取文本的 PDF；扫描版 PDF 暂不支持 OCR。

题库和评分质量可重复审计：

```powershell
.\.venv\Scripts\python.exe scripts\audit_question_bank.py
.\.venv\Scripts\python.exe scripts\evaluate_scoring.py
```

评分校准集中的高/中/低标签目前是开发期临时分档，不等于教师或团队人工分。正式调整 AI 与规则融合权重前，应先做盲评并补入人工标签。

示例生成随机密钥：

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

外部服务凭据只允许放在本地 `.env` 或部署环境变量中。不要将 `.env`、真实数据库或密钥提交到 Git 和参赛压缩包。

如果密钥曾经出现在终端截图、聊天记录或任何已共享文件中，应立即到对应服务商控制台撤销并重新生成；仅从仓库删除文件不能使已经泄露的密钥失效。

## 3. 初始化数据库

初始化表结构并导入岗位、题库和知识种子数据：

```powershell
python scripts\init_db.py --seed
```

如需创建管理员，先在 `.env` 中设置至少 8 位的 `DEMO_ADMIN_PASSWORD`，再执行：

```powershell
python scripts\init_db.py --seed --create-admin
```

默认数据库位置为 `instance/interview.db`。初始化命令可以重复执行，不会重复导入相同题目。
当旧版运行数据库存在时，初始化命令也会应用 MVP 所需的增量字段。

## 4. 启动系统

```powershell
python run.py
```

默认访问地址：<http://127.0.0.1:5001>

健康检查地址：<http://127.0.0.1:5001/api/health>

开发模式默认不会打开 Flask 调试器。如确实需要，可在 `.env` 中设置 `FLASK_DEBUG=true`。生产环境必须设置 `APP_ENV=production` 和 `FLASK_SECRET_KEY`。

## 5. 执行测试

```powershell
pytest
python -m compileall app scripts config.py run.py
```

测试使用临时 SQLite 数据库，不调用真实的大模型或语音服务。

其中 `tests/test_e2e.py` 会使用完整种子数据离线跑通 Java 后端与 Web 前端两个岗位的注册、抽题、回答、规则评分、报告和趋势链路。

## 6. 发布包检查

提交前先确认所有改动已提交，再运行：

```powershell
.\scripts\build_release.ps1
```

脚本先检查 Git 已跟踪文件和最终 ZIP，拒绝 `.env`、数据库、虚拟环境、日志、私钥、常见 API Key 或外部 CDN 依赖。默认输出 `dist/ai-interview-mvp.zip`。

## 7. 个人数据与安全

- 用户在“个人中心”可以将自己的账号、面试、评分、表达指标和训练任务导出为 JSON。
- 删除账号必须再次输入当前密码，删除后关联面试数据由数据库级联清理。
- 写请求校验浏览器来源；登录连续失败会在时间窗口内限流。
- API 错误统一返回 JSON，不向前端暴露内部堆栈；响应包含 CSP、禁止嵌入和 MIME 嗅探等安全头。
- 音频只在当前请求内存中处理，不落盘；外部服务密钥只从 `.env` 读取。
- 永久登录会话最长 12 小时，密码长度限制为 8～128 位；生产模式强制要求固定会话密钥并启用 Secure Cookie。
- 发布前可运行 `python scripts/verify_release.py`、`python -m bandit -r app scripts config.py run.py` 和 `python -m pip_audit -r requirements.txt`。

安全漏洞请按照 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue 中提交密钥、用户数据或可直接利用的细节。

## 配置说明

| 变量 | 必需 | 说明 |
|---|---|---|
| `APP_ENV` | 否 | `development`、`testing` 或 `production` |
| `FLASK_SECRET_KEY` | 生产必需 | Flask 会话签名密钥 |
| `DATABASE_URL` | 否 | 留空时使用 `instance/interview.db` |
| `QUESTIONS_PER_SESSION` | 否 | 数据库尚无业务配置时的默认题目数 |
| `LLM_API_KEY` | 否 | OpenAI 兼容服务密钥 |
| `LLM_API_BASE` | 否 | OpenAI 兼容 API 地址 |
| `LLM_MODEL` | 否 | 模型名称 |
| `XFYUN_APP_ID` | 否 | 讯飞语音识别 AppID |
| `XFYUN_API_KEY` | 否 | 讯飞语音识别 API Key |
| `XFYUN_API_SECRET` | 否 | 讯飞语音识别 API Secret |
| `ASR_TIMEOUT_SECONDS` | 否 | 讯飞语音识别整体超时基准，默认 20 秒 |
| `ASR_MAX_AUDIO_BYTES` | 否 | 单次 WAV 文件最大字节数，默认 4 MB |
| `ASR_MAX_DURATION_SECONDS` | 否 | 单次录音最长时长，最大 60 秒 |
| `TRUSTED_ORIGINS` | 否 | 额外允许提交写请求的浏览器来源，逗号分隔 |
| `LOGIN_MAX_FAILURES` | 否 | 同一来源与账号在窗口内允许的失败次数 |
| `LOGIN_FAILURE_WINDOW_SECONDS` | 否 | 登录失败限流窗口，默认 300 秒 |

## 数据目录

- `seed/`：可提交的岗位、题库和知识数据。
- `instance/`：本地运行数据库，不提交。
- `data/interview.db`：旧版数据库，仅用于一次性迁移，不应继续分发。

如需从旧数据库重新导出非敏感种子数据：

```powershell
python scripts\export_seed_data.py --source data\interview.db --output seed
```

导出脚本只读取岗位、题目和知识表，不导出用户、会话、消息、报告和系统配置。

## 当前 MVP 限制

- 四个岗位均已接入逐题评分点、参考答案知识块和本地缺失点追问；配置 LLM 后自动使用 AI 增强追问与混合评分。
- 未配置 LLM 时使用确定性的本地规则评分，报告会明确标记评分来源；自动生成的评分点仍需持续人工复核。
- 语音回答会记录时长，并根据转写文本计算语速、填充词和重复表达；未采集时间戳、音高和音量时，不推断停顿、情绪或自信度。
- 报告会聚合同类缺失点，并生成 3～5 个包含学习材料、练习题、回答框架和建议复测时间的岗位化训练任务。
- 用户可以从报告训练任务直接创建一场 3 题专项面试；系统会验证报告归属，并只补充同岗位、同主题或同题型题目。
- 进行中的面试会保存到数据库；刷新页面或关闭后重新登录可自动恢复，未自动恢复时可从“未完成的面试”继续。
- 完整回答最后一题后会进入评分状态并自动生成报告；生成失败时回答仍会保留，可重新进入该场次重试。
- 用户可以主动放弃仍在作答或评分失败的场次；历史记录会保留并标记为“已放弃”。
- 仅当前题仍处于追问阶段的最新回答可以编辑；进入下一题后答案锁定，避免追问和评分依据不一致。
- 语音回答会分别保存原始 ASR 转写和用户确认文本；编辑确认文本后重新计算文本类表达指标，录音时长保持不变。
- SQLite 每个连接强制启用外键；题目删除采用停用而非物理删除，已被专项训练引用的来源场次禁止提前删除。
- 成绩趋势只比较最近一次正式面试所属岗位和评分版本；正式面试与专项训练场次分开统计。
- Python 和网络安全的评分点由参考答案自动生成，核心题目仍需进行人工专家复核。
- 专项训练是三题定向复测，页面显示的总分变化仅是与来源完整面试的训练参考，不是严格同卷实验。
- 开发服务器仅供本机演示；公网部署应改用生产 WSGI、HTTPS、反向代理和持久化限流存储。
- 当前 36 份评分校准样本使用开发期临时分档；没有团队或教师盲评分前，不声称其代表人工一致性。

详细实施路线见工作区根目录的 `plan.md`。

## 许可证

代码以 [MIT License](LICENSE) 开源。题库、第三方素材或竞赛资料如另有授权要求，仍以其各自条款为准。

# 公开演示指南

本演示只使用合成数据。除明确标注的 DeepSeek 连通性检查外，其余命令完全离线，不产生 API 费用。

## 1. 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 2. 运行离线智能体

```powershell
.\.venv\Scripts\python.exe scripts\run_agent.py --provider fake "搜索包含 invoice 的邮件"
```

预期结果：智能体调用本地 `search_emails`，返回合成邮件结果并正常结束，不访问真实邮箱。

## 3. 验证 M5.1 数据流控制

```powershell
.\.venv\Scripts\python.exe scripts\run_m51_security.py
```

预期结果：显示 `4/4 passed`。未授权机密数据流进入审批状态，精确授权流和良性操作正常放行。

## 4. 生成 M6 对比报告

```powershell
.\.venv\Scripts\python.exe scripts\run_m6_evaluation.py
```

预期结果：规范化 109 条已有记录，并生成 `results/m6-evaluation-results.json` 和 `results/m6-evaluation-summary.md`。该步骤不会重新调用 DeepSeek。

## 5. 运行发布检查

```powershell
.\.venv\Scripts\python.exe scripts\run_m7_release_check.py
```

只有当工作树干净、`.env` 未被跟踪、秘密扫描和文档链接检查均通过时，仓库才会显示 `release_ready=true`。发布视频应展示上述命令和结果，但不得显示 `.env`、API 密钥或未经脱敏的终端内容。

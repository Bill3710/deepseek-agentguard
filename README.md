# DeepSeek AgentGuard

面向 DeepSeek 工具调用智能体的安全实验与评测项目。

DeepSeek AgentGuard 用一个完全本地、使用合成数据的办公助理环境，复现间接提示注入、越权工具调用和敏感数据外泄，并验证确定性权限策略能否在尽量不影响正常任务的前提下阻止攻击。

> 当前状态：早期开发阶段。仓库已完成基础结构和测试配置，Agent、策略引擎与评测功能仍在实现中，请勿用于生产环境。

## 项目目标

- 构建具备邮件检索、文件读取、模拟发信和记忆写入能力的工具调用 Agent。
- 复现来自邮件、文档和工具输出的间接提示注入。
- 在工具真正执行前完成参数校验、权限判断和人工审批。
- 记录完整调用轨迹，区分模型建议、策略决策与工具执行结果。
- 量化正常任务成功率、攻击成功率、误拦截率、延迟和调用成本。

## 威胁场景

第一阶段聚焦以下攻击链：

```text
用户要求总结项目邮件
        ↓
Agent 读取含恶意指令的邮件
        ↓
恶意内容诱导 Agent 读取机密文件
        ↓
Agent 尝试调用 send_email 外传数据
        ↓
策略引擎允许、阻止或请求人工确认
```

邮件、文件、收件人和“机密数据”均为本地生成的测试数据。项目不会连接真实邮箱，也不会向外部地址发送邮件。

## 设计原则

1. **模型不拥有最终执行权**：DeepSeek 只提出工具调用，策略引擎决定是否执行。
2. **所有模型输出均不可信**：工具名称和参数必须经过白名单与 Pydantic Schema 校验。
3. **数据不能授权操作**：邮件、文件和搜索结果可以提供信息，但不能授予新的工具权限。
4. **最小权限**：工具按读取、写入、可逆性和数据影响分级。
5. **可复现评测**：正常任务和攻击任务使用固定测试集，并保存结构化审计结果。

## 计划中的架构

```text
User Task
   ↓
DeepSeek Provider
   ↓ proposed tool call
Schema Validation
   ↓
Policy Engine ───→ Block / Require Approval
   ↓ allow
Simulated Tool
   ↓
Audit Log + Evaluation Metrics
```

## 仓库结构

```text
deepseek-agentguard/
├── src/agentguard/       # Agent、模型适配器、工具、策略与审计模块
├── tests/                # 单元测试与安全回归测试
├── data/                 # 合成邮件和文件
├── attacks/              # 攻击案例定义
├── docs/                 # 威胁模型和设计文档
├── scripts/              # 本地开发与评测脚本
├── results/              # 可公开的聚合评测结果
├── .env.example          # 环境变量模板，不包含真实密钥
└── pyproject.toml        # Python 项目与依赖配置
```

## 环境要求

- Windows、macOS 或 Linux
- Python 3.11 或更高版本
- Git
- DeepSeek API Key，仅在线评测需要

Docker、Node.js 和本地 GPU 不是第一阶段的必要条件。

## 本地安装

以下命令适用于 Windows PowerShell：

```powershell
git clone https://github.com/Bill3710/deepseek-agentguard.git
Set-Location deepseek-agentguard

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

不需要激活虚拟环境，可以直接使用 `.venv` 中的 Python。

## 配置 DeepSeek API

先复制公开模板：

```powershell
Copy-Item .env.example .env
notepad .env
```

在本地 `.env` 中填写：

```text
DEEPSEEK_API_KEY=你的本地密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
USE_REAL_MODEL=true
```

不要把真实密钥写入 `.env.example`、源代码、测试数据或日志。提交前确认 `.env` 已被忽略：

```powershell
git check-ignore -v .env
git ls-files .env
```

第二条命令应当没有输出。

## 运行测试

运行不产生 API 费用的本地测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

检查代码质量：

```powershell
.\.venv\Scripts\python.exe -m ruff check .
```

在线测试将使用 `online` 标记与普通测试隔离，避免持续集成或本地测试意外产生费用：

```powershell
.\.venv\Scripts\python.exe -m pytest -m online
```

在线测试功能将在 DeepSeek Provider 完成后启用。

## 计划评测指标

| 指标 | 含义 |
|---|---|
| Benign Task Success Rate | 无攻击时正常任务的完成比例 |
| Attack Success Rate | 攻击导致违规工具行为的比例 |
| False Positive Rate | 正常操作被策略错误阻止的比例 |
| Average Tool Calls | 每次任务平均工具调用次数 |
| Latency | 防御策略增加的响应时间 |
| Estimated Cost | 在线模型评测的估算费用 |

## 开发路线

- [x] 初始化项目结构、依赖和基础导入测试
- [ ] 实现本地模拟工具与 Schema
- [ ] 实现 DeepSeek Provider 和 Fake Provider
- [ ] 建立无防御 Agent 基线
- [ ] 复现间接提示注入与数据外泄
- [ ] 实现权限策略、审批和审计日志
- [ ] 建立自动化攻防评测
- [ ] 发布实验结果、架构图和演示视频

## 安全与负责任使用

本项目只用于防御性研究、教学和授权测试。请勿连接真实邮箱、支付系统、云存储或生产数据。发现本仓库自身的安全问题时，请遵循 [SECURITY.md](SECURITY.md)。

## 参考资料

- [DeepSeek API 文档](https://api-docs.deepseek.com/zh-cn/)
- [OWASP Agentic Security Initiative](https://genai.owasp.org/initiatives/agentic-security-initiative/)
- [AgentDojo](https://github.com/ethz-spylab/agentdojo)

---

English summary: DeepSeek AgentGuard is an early-stage defensive research project for reproducing and evaluating prompt-injection attacks against tool-using agents. All tools and data are simulated, and no production systems are accessed.

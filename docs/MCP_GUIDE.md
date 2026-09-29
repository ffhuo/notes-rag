# notes-rag MCP 接入使用说明

[English](MCP_GUIDE_EN.md) | 简体中文

把你的个人知识库接入 AI 助手(Trae / WorkBuddy / OpenClaw 等),让 agent 直接**检索、读原文、问答**你的笔记 —— 不用切窗口、不用手动复制粘贴。

---

## 1. 接入后能做什么(效果)

接入前:agent 只知道自己训练数据里的东西,不认识你的笔记。

接入后:agent 拿到一组「笔记工具」,你的 Obsidian 库变成它的外挂记忆:

| 你说 | agent 的行为 | 你得到 |
|---|---|---|
| 「我笔记里关于 Go sync.Mutex 的内容有哪些?」 | 调用 `search_notes` 语义检索 | 带出处的命中清单:哪篇笔记、哪一段、相关度多少 |
| 「结合我的笔记,讲讲 RAG 里 chunk 策略怎么选」 | 先 `search_notes` 拿你自己的笔记片段,再结合自身知识组织回答 | 一份「你的观点 + 通用知识」融合的回答,引用真实笔记路径 |
| 「我有哪些笔记库?」 | 调用 `list_vaults` | vault 清单:名称、笔记数、索引状态 |
| 「读一下 `notes/example.md` 全文」 | 调用 `get_note` | 整篇笔记原文,agent 可继续分析/总结 |
| 「基于我的笔记回答:Go 的 channel 怎么用?」 | 调用 `ask_notes`(本服务完成检索 + 组织答案) | 整合后的答案 + 引用来源清单 |

**一句话效果:你的笔记从「要自己翻的文件」变成「agent 随口就能问的记忆」。** 因为 agent 拿到的是带出处的真实片段(而不是它自己编的),回答可信度显著更高 —— 每条结论都能点回原始笔记。

> 数据边界:agent 只能以「你签发给它的那把 key」对应的身份访问 —— 你的库对它可见,别人的库不可见(多用户模式);不想让它访问了,在 Web 端一键撤销 key 即可。

---

## 2. 前置条件

接入前确认服务端已就绪(三件事,均在前端完成):

1. **服务在跑**:本机 `make dev`(或 Docker),`http://localhost:8000/healthz` 返回 ok
2. **模型已配置**:「模型」页至少配好一个 kind=embed 的向量模型(检索必需;用 `ask_notes` 还需再配一个 kind=llm)
3. **vault 已索引**:「Vaults」页已添加 vault 且至少跑过一次同步(否则检索返回空)

两种传输方式的前置差异:

| 传输 | 额外前置 |
|---|---|
| stdio(本地子进程) | 项目代码与本机 python 虚拟环境可用 |
| 远程 HTTP | agent 所在机器能访问服务地址(跨机部署需放通端口或经反向代理) |

---

## 3. 接入步骤

### 第 1 步:签发一个用户级 API Key

Web 端「设置 → API Keys」页(或 curl):

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/api-keys \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <你的全局key,若已配置>" \
  -d '{"name": "workbuddy"}'
```

响应里的 `key`(`nr_` 开头)**只出现这一次**,立即复制保存 —— 关掉就再也看不到,丢了只能撤销重建。

这把 key 就是 agent 的身份凭据:它决定了 agent 能看见哪些 vault,也决定撤销时「断谁的电」。

### 第 2 步:配置 agent 的 MCP

下面两种方式**二选一**,按 agent 与服务的部署位置决定。

#### 方式 A:stdio(推荐本地自用)

agent 以子进程方式拉起 MCP server,零端口、最省事。编辑 agent 的 MCP 配置文件(如 `~/.workbuddy/mcp.json`、Trae 的 MCP 设置),加一项:

```json
{
  "mcpServers": {
    "notes-rag": {
      "command": "<本仓库绝对路径>/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "env": { "NOTES_RAG_API_KEY": "nr_粘贴你的key" }
    }
  }
}
```

- `command` 写**绝对路径**,把 `<本仓库绝对路径>` 换成你 clone 本仓库的位置,指向其中的 `.venv/bin/python`
- agent 会在启动时拉起这个子进程,随 agent 启停,不占端口
- 单用户且未配全局 Key 的本机自用场景可省掉 `env`(此时身份为 `default`);其他情况**必须**提供,否则进程启动即退出(fail fast,见 §5)

#### 方式 B:远程 HTTP(推荐跨机 / 集中部署)

MCP 端点挂在主服务上,与 REST 同端口同进程,agent 通过 URL 直连:

```json
{
  "mcpServers": {
    "notes-rag": {
      "url": "http://localhost:8000/mcp/",
      "headers": { "X-API-Key": "nr_粘贴你的key" }
    }
  }
}
```

要点:

- 地址为 `<服务地址>/mcp/`,**末尾斜杠不能省**:该端点由 Starlette 的 Mount 托管,只匹配带尾斜杠的路径,写成 `/mcp` 会返回 405 或返回前端页面(见 §5)。跨机访问把 `localhost` 换成服务主机的 IP / 域名。
- **`headers` 必填**:每一次工具调用都会用请求头里的 `X-API-Key` 重新解析身份,不带就是 401。
- 生产部署建议置于**反向代理之后**并启用 HTTPS —— 本端点未做 DNS rebinding 防护(见 §7),安全边界依赖这把 key,明文 HTTP 下 key 会裸奔。
- 优势:服务只跑一份,多个 agent / 多台机器共用;能力随服务端升级即时生效,agent 侧不用改配置。

### 第 3 步:重启并验证

1. 重启 agent(MCP 列表在启动时加载),在连接器管理页对新 server 点「信任」
2. 对 agent 说:「**列出我的笔记库**」—— 它应调用 `list_vaults` 并返回你的 vault 清单
3. 看到 vault 清单即接入成功 ✅

---

## 4. 可用工具一览

一期**只读**,共 4 个工具:

| 工具 | 作用 | 典型触发语 |
|---|---|---|
| `search_notes(query, top_k?, vault_id?)` | 语义检索,返回命中片段 + 出处(`file_path` / `title` / `score` / `vault_id`) | 「帮我找笔记里关于 XX 的内容」 |
| `get_note(file_path, vault_id?)` | 按相对 vault 根的路径读取整篇笔记原文 | 「打开/读一下某篇笔记」 |
| `list_vaults()` | 列出 vault 与索引状态(`note_count` / `indexed_at` 等) | 「我有哪几个库」 |
| `ask_notes(question, vault_id?, conversation_id?, top_k?)` | 检索增强问答,返回整合答案 + 引用(适合哑客户端;Trae / WorkBuddy 这类 agent 建议用 `search_notes` 自己组织,更省 token) | 「基于笔记回答我 XX」 |

约定与边界:

- `vault_id` 可省略的**前提是当前身份只有一个 vault**;存在多个 vault 时会明确报错并列出可选值,不会静默挑一个(选错库比报错危险)。
- `get_note` 单篇上限 1MB,超限会提示改用 `search_notes` 取片段;路径解析后必须落在 vault 根内,越界请求会被拒。
- `search_notes` / `get_note` 不消耗 LLM 额度,agent 可放心多次调用补足上下文。

> 工具的 docstring 是 agent 判断「何时调用」的依据 —— 如果 agent 该用而没用,优先检查 `app/mcp/server.py` 里工具描述是否写清了「什么时候该用我」。

---

## 5. 排错速查

| 现象 | 原因 | 处理 |
|---|---|---|
| agent 里根本看不到 notes-rag 工具 | MCP 配置格式错 / python 路径不对(方式 A)或 URL 不通(方式 B) / 未重启 | 方式 A 先命令行跑 `<python> -m app.mcp.server` 看是否报错;方式 B 先 `curl` 探端点;改完必须重启 agent |
| (stdio)server 起动即退出 | `NOTES_RAG_API_KEY` 缺失/无效/已撤销(fail fast 是故意的) | 重新签发 key,更新配置里的 `env` |
| 工具报「鉴权失败」/ HTTP 401 | 方式 B 未带 `X-API-Key` 头,或 key 不对 | 检查配置里的 `headers`;确认 key 未被撤销 |
| `POST /mcp` 返回 405、`GET /mcp` 返回网页 | 配置里的 URL 少了末尾斜杠(挂载点只匹配 `/mcp/`) | 把 URL 改成 `http://<host>:8000/mcp/` |
| `GET /mcp/` 直接访问报 400 | 属正常:该端点走 Streamable HTTP 协议,裸 GET 缺会话头 | 用支持 MCP 的客户端接入,不要当普通 REST 调 |
| `search_notes` 返回空 | vault 还没跑过索引,或检索模型与建索引用的不一致 | 到「Vaults」页提交一次同步;检查「模型」页 embed 配置 |
| 工具报「尚未配置向量模型」 | 当前身份下无 kind=embed 配置 | 到「模型」页新增一个 kind=embed 的配置后重试 |
| 工具报「vault(id=N) 尚未建索引」 | vault 存在但从未同步过 | 到「Vaults」页提交一次 sync 作业 |
| 工具报「未用此 embedding 模型建过索引」 | 换过 embed 模型但没重建索引 | 到「Vaults」页重新同步(重建索引) |
| `ask_notes` 报「尚未配置 LLM」 | 无 kind=llm 配置 | 到「模型」页新增一个 kind=llm 配置 |
| 多用户模式下查到了别人的库 | 理论不应发生(按 user_id 隔离) | 检查 key 是否签发给了对的账号;发现越权立即撤销并反馈 |
| 回答里没有出处 | agent 用了自己的知识而非检索结果 | 提问时明说「**在我的笔记里**找…」,或检查工具描述 |

---

## 6. 其他 agent 接入(OpenClaw / curl 直调)

- **OpenClaw**:`~/.openclaw/mcp.json` 格式与 §3 完全一致,stdio 与 HTTP 两种写法照抄即可
- **没有 MCP 支持的 agent**:仓库附带 Skill 文本说明(见 M09 §5.4),教 agent 用 `curl` 直接调 `/api/v1/search`,零部署
- **脚本 / 服务间调用**:不走 MCP,直接 REST + `X-API-Key` 头即可(同一把用户级 key)

---

## 7. 实现状态

| 项 | 状态 |
|---|---|
| 用户级 API Key 签发/撤销 | ✅ 已实现(`api_keys` 表 + `/api/v1/auth/api-keys`,见 M06 §5.7) |
| `search_notes` / `get_note` / `list_vaults` / `ask_notes` | ✅ 已实现(复用 services 层,只读;见 `app/mcp/server.py`) |
| stdio 传输 + 预先授权 | ✅ 已实现(`python -m app.mcp.server`,启动解析身份并 fail fast) |
| Streamable HTTP 传输 | ✅ 已实现(挂载于 `/mcp/`,逐请求按请求头解析身份;URL 须带尾斜杠) |
| 写类工具(ingest)异步适配 | ⏸ 二期:索引是异步作业,agent 侧如何跟进(轮询 / 阻塞等待)尚未定案,一期保持只读 |

鉴权链:全局 `X-API-Key` → 用户级 API Key(`api_keys` 表,`nr_` 开头)→ `Authorization: Bearer <JWT>`,三条链路复用同一份 `resolve_user_id`(`app/core/security.py`),REST 与 MCP 不会出现规则漂移。

已知边界:

- **MCP 端点未在 initialize 阶段鉴权**,身份在每次**工具调用**时才校验。协议握手(列工具等)不返回任何用户数据,数据访问路径全部受 key 保护。
- **DNS rebinding 防护已关闭**(`TransportSecuritySettings(enable_dns_rebinding_protection=False)`):该防护要求预设 allowed_hosts,而部署主机名因环境而异,开启会让所有请求 421。边界由用户级 key 保证(浏览器不会自动携带自定义头),生产环境请置于反向代理后并在那一层做 Host 白名单 + HTTPS。

关联设计:M09(agent-mcp)· M06 §5.7(用户级 API Key)· M03 §5.13(异步作业)· `docs/design.md` §14

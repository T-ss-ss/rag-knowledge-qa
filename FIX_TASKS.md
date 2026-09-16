# RAGent 代码修复任务清单

> 项目路径：`D:\PyCharm Community Edition 2025.2.6\RAGtest1`
> 技术栈：Python 3.12 · FastAPI · ChromaDB · SQLite(WAL) · DeepSeek · Qwen Embedding · BGE-Reranker · Tavily
> 共 13 项，按优先级排列。P0 必须改（会报错/功能未生效），P1 建议改，P2 可选。

---

## 全局约束（务必遵守）

1. **只做清单里列出的事**，不要顺手重构其他文件、不要改目录结构、不要升级依赖版本。
2. **不要动这些文件**：`static/chat.html`（除 FIX-07 要求外）、`test_runner.py`、`TEST_CHECKLIST.md`、`main.py` 里的首页 HTML 字符串。
3. **`app/routers/upload.py` 的 `upload_file` 必须保持 `async def`** —— 函数体里有 `await file.read()`，改成 `def` 会直接报错。
4. 每完成一项，**说明改动的文件和行号，并给出验证方法**（命令或操作步骤）。
5. 改完后**不要自动 commit**，等确认。

---

## P0 — 必修

### FIX-01 ⭐ 最高优先级：Agent 多轮对话第二轮会 400

**问题**
`app/services/agent_service.py` 的 `_build_messages()`（第 123-133 行）在把历史消息注入 LLM 时，**只过滤了 `role == "assistant"` 的占位文本，没有过滤 `role == "tool"` 的消息**。

而 `_save_tool_messages()`（第 139-140 行）会往 `messages` 表写一条 `role="tool"`、内容为 `[工具返回: N 字符]` 的记录。`MsgRepo.list_recent()`（`app/repositories/msg_repo.py:44-53`）不做角色过滤，原样取出。

**后果**
同一会话中第二次提问时，这条 `role="tool"` 的消息会被塞进 `messages` 数组，且**没有 `tool_call_id` 字段**。OpenAI / DeepSeek 的 Chat Completions API 要求 tool 角色的消息必须带 `tool_call_id`，否则返回 `400 Bad Request`。

**注意**：`app/services/chat_service.py:61` 的写法是正确的（`if role not in ("user", "assistant"): continue`），Agent 路径漏了这一行。修复时请与之保持一致。

**文件**：`app/services/agent_service.py`

**当前代码（第 123-133 行）**
```python
    def _build_messages(self, conversation_id: str, question: str) -> list[dict]:
        history_msgs = self.msg_repo.list_recent(conversation_id, 40)
        messages = [{"role": "system", "content": self.system_prompt}]
        for msg in history_msgs:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "assistant" and content and (content.startswith("[调用工具") or content.startswith("[工具返回")):
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})
        return messages
```

**目标代码**
```python
    def _build_messages(self, conversation_id: str, question: str) -> list[dict]:
        history_msgs = self.msg_repo.list_recent(conversation_id, 40)
        messages = [{"role": "system", "content": self.system_prompt}]
        for msg in history_msgs:
            role = msg.get("role", "")
            content = msg.get("content", "")
            # tool / system / function 角色不能注入 LLM：
            # tool 消息缺少 tool_call_id 会导致 API 返回 400
            if role not in ("user", "assistant"):
                continue
            # 过滤 Agent 模式产生的工具调用占位文本
            if role == "assistant" and content and (
                content.startswith("[调用工具") or content.startswith("[工具返回")
            ):
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})
        return messages
```

**验收**
在同一个会话里连续问两个都需要检索文档的问题（例如先问"这份文档讲了什么"，再问"作者是谁"）。第二次请求应正常返回，不再出现 400。

---

### FIX-02 ⭐ Reranker 实际从未执行过

**问题**
`app/config.py` 中 `rerank_enabled: bool = False` 是默认值，而项目的 `.env` **没有配置 `RERANK_ENABLED`**。`app/services/rag_pipeline.py:23` 的判定条件是：

```python
if rerank_enabled and settings.rerank_enabled and len(documents) > top_k:
```

`settings.rerank_enabled` 恒为 `False` → **BGE-Reranker 从来没有被调用过**。旁证：项目根目录没有 `models/` 目录（FlagEmbedding 的 HuggingFace 缓存不存在），说明模型从未下载。

**要做的事**（两步，都要）

**第 1 步**：在 `.env` 中显式开启（放在 `EMBEDDING_BATCH_SIZE` 之后）：
```
RERANK_ENABLED=true
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RETRIEVAL_MULTIPLIER=3
AGENT_MAX_ITERATIONS=5
```

**第 2 步**：`app/config.py` 保持 `rerank_enabled: bool = False` 作为默认值不变（冷启动更友好，避免新用户被迫下载 1.5GB 模型），但要在该字段上方加一行注释说明用途：

```python
    # Reranker
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    # 默认关闭：首次开启会在使用前下载约 1.5GB 模型。
    # 需要在 .env 中显式设置 RERANK_ENABLED=true 才会生效。
    rerank_enabled: bool = False
```

**第 3 步**：`.env.example` 中 `RERANK_ENABLED=false` 后面补一句注释：
```
# 设为 true 启用 BGE 精排（首次使用会下载约 1.5 GB 模型）
RERANK_ENABLED=false
```

**验收**
1. 把 `.env` 的 `RERANK_ENABLED` 设为 `true`，启动服务。
2. 上传一个文档，提一个能检索到内容的问。
3. 观察第一次请求是否触发模型下载（`models/` 目录出现文件）。
4. 在 `app/services/reranker_service.py:19` 的 `logger.info` 处确认日志输出 `Reranker model ... loaded.`

---

### FIX-03 RerankerService 每个请求都重新加载模型

**问题**
`app/services/rag_pipeline.py:24` 在**函数体内部**创建实例：

```python
        reranker = RerankerService()
```

`RerankerService._model` 是实例属性（`app/services/reranker_service.py:10`），所以每个请求都会新建一个实例 → 每次都会重新执行 `FlagReranker(...)`，即**每个请求重新加载一次约 1.5GB 的模型**。"惰性加载"只在单个实例内成立。

对比：`VectorStoreService` 是在 `main.py` 的 `lifespan` 里创建的单例（`main.py:29`），两者做法不一致。

**文件**：`app/services/rag_pipeline.py`

**当前代码（第 1-3 行、第 23-25 行）**
```python
from app.config import settings
from app.services.reranker_service import RerankerService
```
```python
    if rerank_enabled and settings.rerank_enabled and len(documents) > top_k:
        reranker = RerankerService()
        documents, metadatas = reranker.rerank(question, documents, metadatas, top_k)
```

**目标代码**

文件头部改为：
```python
import threading

from app.config import settings
from app.services.reranker_service import RerankerService

_reranker: RerankerService | None = None
_reranker_lock = threading.Lock()


def _get_reranker() -> RerankerService:
    """进程内单例：避免每个请求重复加载约 1.5GB 的 Reranker 模型。"""
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                _reranker = RerankerService()
    return _reranker
```

调用处改为：
```python
    if rerank_enabled and settings.rerank_enabled and len(documents) > top_k:
        documents, metadatas = _get_reranker().rerank(
            question, documents, metadatas, top_k
        )
```

**另外**（可选但建议）：`RerankerService.rerank()` 里调用的 `self._model.compute_score(...)` 是 CPU 推理，同一模型实例被多线程并发调用不保证安全。建议在 `app/services/reranker_service.py` 的 `rerank()` 方法内用锁保护 `compute_score` 调用：

```python
    def rerank(self, question, documents, metadatas, top_k):
        ...
        if self._invoke_lock is None:
            self._invoke_lock = threading.Lock()
        with self._invoke_lock:
            scores = self._model.compute_score(pairs, normalize=True)
```

（在 `__init__` 中加 `self._invoke_lock = None`，文件顶部 `import threading`。）

**验收**
启用 rerank 后连续发两个请求，日志中 `Reranker model ... loaded.` **只应出现一次**。

---

### FIX-04 `/health` 端点会阻塞整个事件循环

**问题**
`main.py:136` 是 `async def health(...)`，函数体内做了两次**同步**的外部网络调用 `client.models.list()`，且新建的 `OpenAI()` 客户端**没有设置 timeout**（openai-python v1 的默认超时是 600 秒）。

**后果**
DeepSeek 或 DashScope 异常时，这个请求会把事件循环阻塞最长 20 分钟，期间**整个服务无法响应任何其他请求**。而健康检查端点通常被监控系统高频轮询，问题会被放大。

**文件**：`main.py`（第 135-179 行）

**目标代码**
```python
@app.get("/health", summary="健康检查")
def health(request: Request):
    """注意：必须是同步 def。函数体内有阻塞式网络调用，
    用 async def 会阻塞事件循环。"""
    vector_store: VectorStoreService = request.app.state.vector_store

    chat_ok = False
    try:
        client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=5.0,
            max_retries=0,
        )
        client.models.list()
        chat_ok = True
    except Exception:
        pass

    embedding_ok = False
    try:
        client = OpenAI(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            timeout=5.0,
            max_retries=0,
        )
        client.models.list()
        embedding_ok = True
    except Exception:
        pass

    # ... 以下保持不变
```

**验收**
断开网络（或填入一个错误的 API Key）后访问 `/health`，应在 5 秒左右返回 `status: "degraded"`，且此时其他接口仍能正常响应。

---

### FIX-05 所有含阻塞调用的端点都应该用 `def`，不能用 `async def`

**问题**
`app/routers/*.py` 的端点绝大多数是 `async def`，但函数体内调用的是**全同步**的代码：OpenAI 同步客户端、`sqlite3`、`chromadb`、`requests`。

`async def` 里的同步阻塞调用会**占住事件循环**，比写成 `def` 更糟 —— 写成 `def` 时 Starlette 会自动把它丢进线程池执行。

**改动规则（逐条对照）**

| 文件 | 行号 | 函数 | 改法 |
|---|---|---|---|
| `app/routers/qa.py` | 27 | `ask_question` | `async def` → `def` |
| `app/routers/knowledge_bases.py` | 32, 44, 52, 63, 80 | 5 个端点 | `async def` → `def` |
| `app/routers/documents.py` | 27, 40 | 2 个端点 | `async def` → `def` |
| `app/routers/conversations.py` | 50, 63, 74, 88, 100, 112, 165 | 7 个端点 | `async def` → `def` |
| `app/routers/conversations.py` | 218 | `conversation_agent_stream` | **保持不变**（见下方说明） |
| `app/routers/upload.py` | 57 | `upload_file` | **保持不变，必须保持 `async def`**（含 `await file.read()`） |
| `main.py` | 59, 131 | `home` / `chat_page` | 保持不变（无阻塞调用） |

**关于 `conversation_agent_stream`（第 218 行）**
它返回 `StreamingResponse`，且传入的是一个**同步生成器**（`agent_service.ask_stream` 是同步生成器）。Starlette 检测到同步迭代器后会自动用 `iterate_in_threadpool` 包装，所以这一处本身是安全的。可以保持 `async def`，也可以改成 `def`，两种都能工作 —— **按现有写法保持不动即可，减少改动面**。

**注意事项**
- `def` 端点里 `return` 字典、Pydantic 模型、`JSONResponse` 的行为与 `async def` 完全一致，不需要改返回语句。
- `Depends(...)` 依赖注入不受影响。
- 只改函数定义的 `async` 关键字，不要改函数体。

**验收**
把 `app/routers/qa.py` 的 `ask_question` 改成 `def` 后，用并发测试验证：同时发起 3 个 `/api/qa` 请求，三个请求应**并行**处理（总耗时接近单个请求，而不是三倍）。改动前是串行的。

---

## P1 — 建议修（影响一致性/可维护性）

### FIX-06 rerank 开关在两个入口行为不一致

**问题**
- HTTP 入口（`/api/qa`、`/api/conversations/{id}/qa`）：是否精排 = **请求参数 `rerank` AND 全局 `settings.rerank_enabled`**
- Agent 工具入口（`app/services/kb_tool.py:16`）：只用 `settings.rerank_enabled`，**请求参数完全不生效**

**目标**：统一为「请求参数 AND 全局配置」。

**改动 1**：`app/models/schemas.py` 的 `AgentQARequest`（第 165 行）增加 `rerank` 字段，与 `ConversationQARequest` 保持一致：
```python
class AgentQARequest(BaseModel):
    question: str = Field(...)
    top_k: int = Field(default=4, ge=1, le=20, description="检索文档块数量")
    temperature: float = Field(default=0.3, ge=0.0, le=1.0, description="LLM 温度参数")
    rerank: bool = Field(default=True, description="是否启用 BGE-Reranker 精排（需全局 RERANK_ENABLED=true）")
    max_iterations: int = Field(default=settings.agent_max_iterations, ge=1, le=10, description="Agent 最大推理步数")
```

**改动 2**：`app/services/kb_tool.py` 的 `search` 接受 rerank 参数：
```python
    def search(self, question: str, top_k: int = 4, rerank: bool | None = None) -> tuple[str, list[dict]]:
        rerank_enabled = settings.rerank_enabled if rerank is None else (
            rerank and settings.rerank_enabled
        )
        context, sources = retrieve_context(
            self.embedding_service, self.vector_store, self.collection_name,
            question, top_k, rerank_enabled=rerank_enabled,
        )
        return context or "未找到相关文档。", sources
```

**改动 3**：`app/services/agent_service.py`
- `__init__` 增加参数并保存：
```python
    def __init__(self, vector_store, embedding_service, collection_name: str, rerank: bool = True):
        ...
        self.rerank = rerank
```
- `_run_kb_search` 透传：
```python
    def _run_kb_search(self, query: str, top_k: int) -> tuple[str, list[dict]]:
        context, sources = self.kb_tool.search(query, top_k, self.rerank)
        return context or "未找到相关文档。", sources
```

**改动 4**：`app/routers/conversations.py` 中两处构造 `AgentService` 的地方（`conversation_agent` 和 `conversation_agent_stream`）传入 `rerank=body.rerank`。

```python
    agent_service = AgentService(vector_store, embedding_service, collection_name, rerank=body.rerank)
```

> 注意：`agent_service.py` 里有两处调用 `_run_kb_search` 的路径（`_react_loop` 和 `ask_stream`），都通过 `self.rerank` 传递，不需要额外改动。

**验收**
关闭全局 `RERANK_ENABLED` 时，任何入口都不会精排；开启后，请求体传 `rerank: false` 时 Agent 与 RAG 两条路径都应跳过精排。

---

### FIX-07 `relevance_score` 一个字段混用三种量纲

**问题**
`sources` 里的 `relevance_score` 字段在不同路径下含义完全不同：

| 来源 | 计算方式 | 取值范围 | 位置 |
|---|---|---|---|
| ChromaDB 粗筛 | `1.0 - cosine_distance` | **-1 ~ 1**（可能为负） | `app/services/vector_store.py:83` |
| BGE Reranker | sigmoid 归一化分数 | 0 ~ 1 | `app/services/reranker_service.py:59` |
| Tavily 联网 | Tavily 自带的 `score` | 0 ~ 1 | `app/services/web_search_tool.py:56` |

同一个字段名在不同配置下量纲不同，前端展示和阈值过滤都会失真。

**目标**：保留原值不变（不改数值，避免影响已有数据），但**增加一个 `score_type` 字段标明量纲**。

**改动 1**：`app/services/vector_store.py:83`
```python
                metadatas[i]["relevance_score"] = round(1.0 - d, 4)
                metadatas[i]["score_type"] = "cosine"
```

**改动 2**：`app/services/reranker_service.py:59`
```python
            meta["relevance_score"] = round(float(s[2]), 4)
            meta["score_type"] = "rerank"
```

**改动 3**：`app/services/web_search_tool.py` 的 `sources.append({...})` 中增加：
```python
                "score_type": "web",
```

**改动 4**：`app/services/rag_pipeline.py` 的 `build_source_list()`（第 41-51 行）透传该字段：
```python
def build_source_list(documents: list[str], metadatas: list[dict]) -> list[dict]:
    return [
        {
            "document_id": meta.get("document_id", ""),
            "filename": meta.get("filename", "unknown"),
            "page": meta.get("page", 0),
            "content": doc[:500],
            "relevance_score": meta.get("relevance_score", 0.0),
            "score_type": meta.get("score_type", "cosine"),
        }
        for doc, metadatas_item in zip(documents, metadatas)
    ]
```
（注意：`zip` 的第二个变量名不要和参数 `metadatas` 冲突，沿用原来的 `doc, meta` 即可。）

**改动 5**：`app/models/schemas.py` 的 `SourceChunk`（第 64 行）增加字段：
```python
    score_type: str = Field(default="cosine", description="相关度分数的量纲：cosine / rerank / web")
```

**验收**
分别用「关闭 rerank」「开启 rerank」「联网搜索」三种方式提问，返回的 `sources[].score_type` 应分别为 `cosine` / `rerank` / `web`。

---

### FIX-08 `ask_stream` 与 `_react_loop` 是两份重复实现

**问题**
`app/services/agent_service.py` 中，流式（第 230-326 行）与非流式（第 338-381 行）各写了一遍 ReAct 循环。项目在 RAG 层用 `rag_pipeline.py` 做过一次去重重构，Agent 层又出现了同样的问题 —— 面试时容易被追问。

**目标**：抽取共用的「处理一次工具调用」逻辑。**不要重写整个循环**，只抽工具调用的处理部分。

**建议做法**：新增一个方法，把「记录 reasoning_step → 执行工具 → 保存消息 → 追加到 LLM 上下文」这段（在两处几乎逐行相同）合并：

```python
    def _handle_tool_call(
        self, messages: list[dict], tc, tool_name: str, tool_args: str,
        question: str, top_k: int, step: int, reasoning_steps: list[dict],
        all_sources: list[dict], conversation_id: str,
    ) -> tuple[list[dict], list[dict]]:
        """执行一次工具调用，返回 (reasoning_steps_delta, sources_delta)。"""
        reasoning_steps.append({
            "step": step, "type": "tool_call",
            "detail": f"调用 {tool_name}: {tool_args}",
        })

        result_text, sources = self._execute_tool(tool_name, tool_args, question, top_k)
        all_sources.extend(sources)

        reasoning_steps.append({
            "step": step, "type": "tool_result",
            "detail": f"找到 {len(sources)} 条结果",
        })

        self._append_tool_messages(messages, tc, tool_name, tool_args, result_text)
        self._save_tool_messages(conversation_id, tool_name, tool_args, result_text)
        return reasoning_steps, all_sources
```

然后在 `_react_loop`（第 351-370 行）和 `ask_stream`（第 273-298 行）中调用它。`ask_stream` 额外产出两个 SSE 事件，在调用前后单独 yield 即可。

**注意**：`ask_stream` 里 `tool_deltas` 的增量拼接逻辑（第 244-271 行）与非流式的 `msg.tool_calls` 结构不同，**这部分不要强行合并**，只合并工具执行后的公共部分。

**验收**
改动后两条路径的行为与改动前完全一致（用同一组问题分别测流式和非流式），且 `_execute_tool` + 保存消息的逻辑在文件中只出现一处。

---

### FIX-09 Service 层绕过 Repository 直接写 SQL

**问题**
项目文档宣称分层是 `Router → Service → Repository`，但以下位置在 Service 层直接执行了原始 SQL，绕过了 Repository：

- `app/services/chat_service.py:75-107`（用户/助手消息插入 + `message_count` 更新 + 标题回填）
- `app/services/agent_service.py:157-201`（`_finalize` 方法，同样的三件事）

**目标**：把这两处的原始 SQL 下沉到 Repository。**保持 SQL 语句本身不变**，只是搬位置。

**建议做法**：在 `app/repositories/msg_repo.py` 增加一个批量保存方法：
```python
    def add_pair_and_touch_conversation(
        self, conversation_id: str, question: str, answer: str,
        sources: list[dict] | None, model: str | None, title_hint: str,
    ) -> tuple[dict, dict]:
        """在一个事务内保存 user + assistant 两条消息，并更新会话计数与标题。"""
        # 原 chat_service.py:75-104 的逻辑搬到这里，SQL 不变
```
在 `app/repositories/conv_repo.py` 增加计数增量方法（`agent_service` 里 `delta = 2 + 2 * tool_call_count` 的算术应放进 Repository，不要留在 Service）。

> 这一项改动面稍大，如果时间紧可以只做 `chat_service` 那一处，`agent_service._finalize` 保持原样但在注释里说明。

**验收**
`app/services/` 目录下不应再出现 `conn.execute(` / `get_db()` 的调用（`grep` 验证）。

---

### FIX-10 `requests` 未声明在 requirements.txt

**问题**
`app/services/web_search_tool.py:3` 直接 `import requests`，但 `requirements.txt` 中没有声明。目前能跑是因为 `chromadb` 的传递依赖恰好带进了 `requests` —— 属于隐性依赖，干净的 Docker 构建或有依赖变动时会突然失败。

**文件**：`requirements.txt`

**改动**：在 `openai` 那一行之后加入：
```
requests>=2.31.0,<3.0.0
```

**同时修正数字**：`requirements.txt` 现在有 13 个包，而 `README.md:466` 和 `PROJECT_PORTFOLIO.md` 中写的"仅 8 个 PyPI 包"是错的，改为"仅 13 个直接依赖，未引入 LangChain 重型框架（仅使用其文本切分器）"。

**验收**
`pip install -r requirements.txt` 在全新虚拟环境中不报错，且能 `import requests`。

---

## P2 — 可选（改了加分，不改也能讲清楚）

### FIX-11 数据库迁移缺少原子性保护

**问题**
`app/db/database.py:26-46` 的 `_migrate_messages_schema` 用 `conn.executescript()` 执行「建新表 → 搬数据 → 删旧表 → 重命名」。但：

- `executescript()` 会先隐式提交；
- Python `sqlite3` 默认隔离级别下，**DDL 语句不参与隐式事务**（只有 INSERT/UPDATE/DELETE 会）。

所以脚本执行到 `DROP TABLE messages` 之后、`ALTER TABLE messages_new RENAME TO messages` 之前如果进程中断，**旧表已删、新表没改名 → 数据丢失**。

**注意**：SQLite **支持事务性 DDL**，只要显式用 `BEGIN` / `COMMIT` 包起来就是原子的。

**改动要点**
1. 文件顶部补 `import shutil`、`from datetime import datetime`。
2. 迁移前先备份数据库文件。
3. 用 `BEGIN IMMEDIATE; ... COMMIT;` 包住整个迁移脚本。
4. 异常时回滚（`ROLLBACK` 本身要包在 try 里，避免"无活动事务"报错）。

**参考实现**
```python
def _migrate_messages_schema(conn: sqlite3.Connection):
    """Recreate messages table if CHECK constraint is outdated (missing 'tool' role)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()
    if not (row and "role IN ('user', 'assistant')" in row[0]):
        return

    # 迁移前备份数据库文件（init_db 在服务启动阶段执行，此时无并发写入）
    db_path = Path(settings.sqlite_db_path)
    if db_path.exists():
        backup_path = db_path.with_name(
            f"{db_path.name}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        shutil.copy2(db_path, backup_path)

    try:
        conn.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE messages_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool', 'function')),
                content TEXT NOT NULL,
                sources TEXT DEFAULT NULL,
                model TEXT DEFAULT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO messages_new SELECT * FROM messages;
            DROP TABLE messages;
            ALTER TABLE messages_new RENAME TO messages;
            CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id);
            COMMIT;
        """)
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
```

**另外**：`models/` 目录（启用 Reranker 后会生成，约 1.5GB）**没有被 `.gitignore` 覆盖**，请加入：
```
# HuggingFace model cache
models/
```

**验收**
构造一个旧版 schema 的 `app.db`（`messages` 表 CHECK 只允许 `user`/`assistant`），启动服务后：
1. 迁移成功，数据行数不变；
2. 同目录出现 `.bak-<时间戳>` 备份文件；
3. 手动在 `DROP TABLE` 后制造异常，确认原表数据仍完整。

---

### FIX-12 `Sources` 里的页码是估算值，不是真实页码

**问题**
`app/routers/upload.py:96-97`：
```python
    pages_per_chunk = page_count / max(chunk_count, 1)
    pages = [int(i * pages_per_chunk) for i in range(chunk_count)]
```
页码是**按 chunk 序号线性折算**出来的，不是从 PDF 真实页边界得到的。`pdf_service.extract_text()` 返回的是拼好的整篇文本 + 总页数，页边界信息已经丢了。

所以文档中「Sources **精确**引用（文件名、页码）」里的"精确"不成立。

**两条路，任选**

**路线 A（诚实口径，零成本）**：不改代码。把 `README.md` 和 `PROJECT_PORTFOLIO.md` 中"精确引用"的说法改为"标注来源文件与**估算**页码"，并在 `INTERVIEW_ANSWERS.md` 中准备好回答："页码是按 chunk 在文档中的位置线性折算的，不是精确定位；要精确的话需要让 PDF 解析层返回每页的文本边界。"

**路线 B（真修，改动较大但面试含金量高）**：
1. `app/services/pdf_service.py` 的 `extract_text()` 改为返回 `list[tuple[int, str]]`（页码, 该页文本），即 `[(0, page1_text), (1, page2_text), ...]`。
2. `app/services/word_service.py` 做同样处理（Word 可用段落序号作为伪页码）。
3. `app/services/chunking_service.py` 的 `split()` 改为接受 `list[tuple[int, str]]`，**逐页切块**，并为每个 chunk 记录它来自哪一页。
4. `app/routers/upload.py` 用真实的页号列表替换现在的线性折算逻辑。

**验收（路线 B）**
上传一个 10 页的 PDF，提一个明确出自第 7 页的问题，返回的 `sources[].page` 应为 `7`（现在是随机折算值）。

---

### FIX-13 代码整洁性小问题

1. `app/services/vector_store.py:140`：
```python
        except (ValueError, Exception):
```
`ValueError` 被 `Exception` 完全覆盖，是冗余写法，且吞掉了所有异常。改为：
```python
        except Exception as exc:
            logger.warning("delete_collection('%s') failed: %s", collection_name, exc)
```
（文件顶部补 `import logging` 与 `logger = logging.getLogger(__name__)`。）

2. `app/services/rag_pipeline.py:54-59` 的 `extract_summary(text, max_len=100)`：当文本中含 `。` 时直接返回第一句，**不受 `max_len` 约束**，可能远超 100 字符。要么在返回前截断，要么把参数改名以免误导：
```python
def extract_summary(text: str, max_len: int = 100) -> str:
    for sep in ["。", "\n\n", ". "]:
        parts = text.split(sep, 1)
        if len(parts) > 1:
            return parts[0].strip()[:max_len]
    return text[:max_len]
```

3. `.env` 中残留了一个已废弃的键 `CHROMA_COLLECTION_NAME`（`app/config.py` 里已无该字段，因为 `extra="ignore"` 所以不报错）。建议删除该行，避免误导。

---

## 改完后的整体自测清单

```bash
# 1. 语法与导入检查
python -m compileall app main.py

# 2. 启动服务
uvicorn main:app --reload --port 8080

# 3. 健康检查应在 5 秒内返回
curl http://127.0.0.1:8080/health
```

手动验证（按顺序）：

| # | 操作 | 期望 |
|---|---|---|
| 1 | 上传一个 PDF | 200，`chunk_count > 0` |
| 2 | 同会话连问两个需检索的问题（RAG 模式） | 两次都正常，无 400 |
| 3 | 同会话连问两个需检索的问题（**Agent 模式**） | **两次都正常，无 400**（FIX-01 关键验收） |
| 4 | Agent 模式问"今天天气" | 触发 `search_web`，SSE 有 `tool_call` / `tool_result` 事件 |
| 5 | 并发 3 个 `/api/qa` | 并行处理，总耗时接近单个请求（FIX-05 验收） |
| 6 | 开启 `RERANK_ENABLED=true` 后重启，连发 2 次提问 | 日志中模型只加载一次（FIX-03 验收） |
| 7 | 检查返回的 `sources[].score_type` | `cosine` / `rerank` / `web` 三种值都能出现（FIX-07 验收） |

---

## 附：文档口径需要同步修正的地方（改完代码后）

| 文件 | 位置 | 现在写的 | 应改为 |
|---|---|---|---|
| `README.md` | 第 466 行 | 仅 8 个 PyPI 包 | 13 个直接依赖（含 `requests`，另使用 LangChain 的文本切分器） |
| `PROJECT_PORTFOLIO.md` | 4.2 工程亮点 | 仅 8 个 PyPI 包，无 LangChain 重型框架 | 同上，并说明"非 LangChain 实现 Agent"指未用其 Chain/Agent/Memory |
| `INTERVIEW_ANSWERS.md` | Q13 | "Agent 模式：过滤同上" | 补充说明过滤的是 `role not in ("user","assistant")` 的消息 |
| `INTERVIEW_ANSWERS.md` | Q15 | "FastAPI + Uvicorn，异步处理 HTTP 请求" | 补一句：因底层 SDK 均为同步，"非流式端点使用 `def` 交由 Starlette 线程池执行，而非 `async def`" |
| `INTERVIEW_ANSWERS.md` | Q19 | "不会丢数据" | 改为"流程上全量复制所以不丢，但缺少原子性保护，已用 `BEGIN IMMEDIATE` 包裹并增加迁移前备份" |
| `INTERVIEW_ANSWERS.md` | Q22 | "默认 60 秒超时" | openai-python v1 的 `DEFAULT_TIMEOUT` 为 600 秒；代码中已显式设为 5 秒（健康检查）/ 按需设置（业务调用） |
| `INTERVIEW_ANSWERS.md` | Q25 | "测试只写了一部分" | 改为"`test_runner.py`（693 行）+ `TEST_CHECKLIST.md` 8 大类约百条用例覆盖了全链路" |
| `INTERVIEW_ANSWERS.md` | Q26 | "200 页约 400 个 chunk" | 按 `chunk_size=1000` 字符，中文 200 页约 200 个 chunk |
| `README.md` / `PROJECT_PORTFOLIO.md` | 亮点部分 | Sources "精确引用"、页码 | 若走 FIX-12 路线 A，改为"估算页码" |

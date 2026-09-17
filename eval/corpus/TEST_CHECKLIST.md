# RAG 项目完整测试清单

> 生成日期：2026-06-05 | 覆盖版本：当前 master 分支

---

## 目录

1. [知识库管理](#1-知识库管理)（TC-KB-001 ~ TC-KB-012）
2. [文档上传](#2-文档上传)（TC-UP-001 ~ TC-UP-017）
3. [RAG 问答](#3-rag-问答)（TC-RAG-001 ~ TC-RAG-014）
4. [会话管理](#4-会话管理)（TC-CONV-001 ~ TC-CONV-013）
5. [Agent](#5-agent)（TC-AG-001 ~ TC-AG-020）
6. [联网搜索](#6-联网搜索)（TC-WS-001 ~ TC-WS-009）
7. [来源展示](#7-来源展示)（TC-SRC-001 ~ TC-SRC-008）
8. [Rerank](#8-rerank)（TC-RR-001 ~ TC-RR-010）

---

## 1. 知识库管理

### TC-KB-001 — 创建知识库（正常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/knowledge-bases`，body: `{"name": "测试库", "description": "这是一个测试"}` | 返回 200，包含 `id`, `name`, `description`, `document_count: 0`, `created_at` |
| 2 | `GET /api/knowledge-bases` | 列表中包含刚创建的知识库 |

### TC-KB-002 — 创建重名知识库（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 已存在名为 "默认知识库" 的 KB | — |
| 2 | `POST /api/knowledge-bases`，body: `{"name": "默认知识库"}` | 返回 400，error_code: `KB_ALREADY_EXISTS` |

### TC-KB-003 — 创建知识库名称为空（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/knowledge-bases`，body: `{"name": ""}` | 返回 422（Pydantic 校验失败） |

### TC-KB-004 — 创建知识库名称超长（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/knowledge-bases`，body: `{"name": "（51 个字符的字符串）"}` | 返回 422（Pydantic 校验失败），name 限制 1-50 字符 |

### TC-KB-005 — 创建知识库描述超长（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/knowledge-bases`，body: `{"name": "test", "description": "（201 个字符的字符串）"}` | 返回 422，description 限制 0-200 字符 |

### TC-KB-006 — 获取知识库详情

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GET /api/knowledge-bases/{kb_id}` | 返回 200，包含完整 KB 信息 |
| 2 | 传入不存在的 `kb_id` | 返回 404，error_code: `KB_NOT_FOUND` |

### TC-KB-007 — 更新知识库名称

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `PUT /api/knowledge-bases/{kb_id}`，body: `{"name": "新名称"}` | 返回 200，name 已更新 |
| 2 | 再次查询该 KB | name 为 "新名称" |

### TC-KB-008 — 更新知识库名称为已存在的名称（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 存在 KB-A (name="库A") 和 KB-B (name="库B") | — |
| 2 | `PUT /api/knowledge-bases/{KB-A的id}`，body: `{"name": "库B"}` | 返回 400，error_code: `KB_ALREADY_EXISTS` |

### TC-KB-009 — 删除知识库

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `DELETE /api/knowledge-bases/{kb_id}` (非 default) | 返回 200，KB 被删除 |
| 2 | `GET /api/knowledge-bases/{kb_id}` | 返回 404 |
| 3 | 该 KB 下的文档和会话也被级联删除 | 对应文档和会话查询不到 |

### TC-KB-010 — 删除 default 知识库（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `DELETE /api/knowledge-bases/default` | 返回 400，error_code: `DEFAULT_KB_DELETE_FORBIDDEN` |

### TC-KB-011 — 更新不存在的知识库（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `PUT /api/knowledge-bases/nonexistent_id` | 返回 404，error_code: `KB_NOT_FOUND` |

### TC-KB-012 — default 知识库自动创建

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 首次启动应用（无 `./data/app.db`） | 启动完成后自动创建 id="default" 的知识库 |
| 2 | `GET /api/knowledge-bases` | 列表中包含 "默认知识库" |

---

## 2. 文档上传

### TC-UP-001 — 上传 PDF 文件（正常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/upload`，上传一个有效的 PDF 文件（< 50MB），kb_id="default" | 返回 200，包含 `document_id`, `filename`, `page_count`, `chunk_count`, `status: "success"` |
| 2 | `GET /api/documents?kb_id=default` | 列表中包含该文档 |
| 3 | 知识库的 `document_count` 递增 1 | — |

### TC-UP-002 — 上传 DOCX 文件（正常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/upload`，上传一个有效的 .docx 文件，kb_id="default" | 返回 200，`status: "success"` |
| 2 | `GET /api/documents?kb_id=default` | 列表中包含该文档 |

### TC-UP-003 — 上传不支持的格式（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/upload`，上传一个 .txt 或 .png 文件 | 返回 400，error_code: `INVALID_FILE_TYPE`，detail: "Only PDF and DOCX files are accepted." |

### TC-UP-004 — 上传超过大小限制的文件（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/upload`，上传 > 50MB 的文件 | 返回 413，error_code: `FILE_TOO_LARGE` |

### TC-UP-005 — 上传到不存在的知识库（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/upload`，kb_id="nonexistent" | 返回 404，error_code: `KB_NOT_FOUND` |

### TC-UP-006 — 上传空白 PDF（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传一个只有图片/扫描件、无文字层的 PDF | 返回 400，error_code: `EMPTY_PDF` |

### TC-UP-007 — 上传损坏的 PDF（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传一个损坏的/无法解析的 PDF 文件 | 返回 400，error_code: `CORRUPT_PDF` |

### TC-UP-008 — 上传损坏的 DOCX（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传一个损坏的 .docx 文件（或改名为 .docx 的非 Word 文件） | 返回 400，error_code: `CORRUPT_PDF` |

### TC-UP-009 — 上传空内容 DOCX（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传一个没有任何文字内容的 .docx 文件 | 返回 400，error_code: `EMPTY_PDF` |

### TC-UP-010 — 分块数为 0 的边界情况（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传一个文本极少（分块后为 0 个 chunk）的文件 | 返回 400，error_code: `EMPTY_PDF` |

### TC-UP-011 — 上传文件名包含特殊字符

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传文件名含中文/空格/特殊字符的 PDF | 正常成功，filename 字段保留原始文件名 |

### TC-UP-012 — 上传无文件名（filename 为 None）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 模拟上传一个 `filename = None` 的文件 | 系统使用 "unknown.pdf" 作为回退值，正常完成 |

### TC-UP-013 — 同一文件重复上传

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传同一个 PDF 两次 | 两次都成功，生成两个不同的 document_id，各自有独立的 chunks |

### TC-UP-014 — 查看文档列表

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GET /api/documents?kb_id=default` | 返回该 KB 下所有文档，含 `document_id`, `filename`, `page_count`, `chunk_count`, `uploaded_at` |
| 2 | 指定不存在的 kb_id | 返回空列表（无 404，因为 KB 可能不存在但端点不校验 KB） |

### TC-UP-015 — 删除文档

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `DELETE /api/documents/{doc_id}?kb_id=default` | 返回 200，含 `document_id` 和 `status: "deleted"` |
| 2 | `GET /api/documents?kb_id=default` | 该文档不再出现 |
| 3 | 知识库 `document_count` 递减 1 | — |

### TC-UP-016 — 删除不存在的文档（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `DELETE /api/documents/nonexistent_id?kb_id=default` | 返回 404，error_code: `DOCUMENT_NOT_FOUND` |

### TC-UP-017 — 跨知识库文档隔离

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传文件到 KB-A | 成功 |
| 2 | 上传文件到 KB-B | 成功 |
| 3 | `GET /api/documents?kb_id=KB-A的id` | 只显示 KB-A 的文档，不包含 KB-B 的文档 |
| 4 | 在 KB-A 中提问 | 只能检索到 KB-A 的文档内容 |

---

## 3. RAG 问答

### TC-RAG-001 — 基本问答（正常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传一份包含 "Python 是一种编程语言" 的文档到 default KB | 成功 |
| 2 | `POST /api/qa`，body: `{"question": "Python 是什么?", "kb_id": "default"}` | 返回 200，answer 包含文档相关内容，sources 包含文档来源 |

### TC-RAG-002 — 问题为空（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/qa`，body: `{"question": ""}` | 返回 422，question 限制 1-2000 字符 |

### TC-RAG-003 — 问题超长（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/qa`，body: `{"question": "（2001 个字符）"}` | 返回 422 |

### TC-RAG-004 — top_k 边界值

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/qa`，body: `{"question": "...", "top_k": 1}` | 正常，返回 1 个来源 |
| 2 | `POST /api/qa`，body: `{"question": "...", "top_k": 20}` | 正常 |
| 3 | `POST /api/qa`，body: `{"question": "...", "top_k": 0}` | 返回 422（范围为 1-20） |
| 4 | `POST /api/qa`，body: `{"question": "...", "top_k": 21}` | 返回 422 |

### TC-RAG-005 — temperature 边界值

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `temperature: 0.0` | 正常 |
| 2 | `temperature: 1.0` | 正常 |
| 3 | `temperature: -0.1` | 返回 422 |
| 4 | `temperature: 1.01` | 返回 422 |

### TC-RAG-006 — 空知识库问答（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 创建一个新 KB，不上传任何文档 | — |
| 2 | `POST /api/qa`，body: `{"question": "测试", "kb_id": "（新KB的id）"}` | 返回 200（非错误状态码），answer 为 "该知识库中还没有文档，请先上传 PDF。" |

### TC-RAG-007 — 知识库中无相关文档

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传一份关于 "Python" 的文档 | 成功 |
| 2 | 提问 "量子力学是什么？" | answer 包含 "根据已有文档无法回答此问题。" |

### TC-RAG-008 — 跨知识库数据隔离

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | KB-A 上传 Python 文档，KB-B 上传 Java 文档 | — |
| 2 | 在 KB-A 中提问 "Java 是什么？" | 无法从 KB-A 的 Python 文档中找到 Java 相关内容，返回 "无法回答" |
| 3 | 在 KB-A 中提问 "Python 是什么？" | 正常检索到 Python 相关内容 |

### TC-RAG-009 — kb_id 为不存在的知识库（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/qa`，body: `{"question": "...", "kb_id": "nonexistent"}` | 返回 404，error_code: `KB_NOT_FOUND` |

### TC-RAG-010 — retrieval_top_k 参数

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `retrieval_top_k: 0` | 系统自动使用 `top_k * retrieval_multiplier`（默认 4 × 3 = 12）做粗筛 |
| 2 | `retrieval_top_k: 20` | 系统粗筛 20 条再精排 |
| 3 | `retrieval_top_k: 100` | 正常（最大值） |
| 4 | `retrieval_top_k: 101` | 返回 422 |

### TC-RAG-011 — 无会话的一次性问答（/api/qa）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/qa` 提问 | 返回答案 + 来源，不依赖会话上下文 |
| 2 | 再次提问（不同问题） | 每次独立检索，不受历史影响 |

### TC-RAG-012 — 回答使用中文

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传中文文档，提问 | answer 为中文回复 |

### TC-RAG-013 — 答案摘要生成

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 正常提问 | 响应中 `summary` 字段包含首句摘要（不超过 200 字符） |

### TC-RAG-014 — 响应包含 sources 字段

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 正常提问，检索到 N 条相关 chunk | `sources` 数组中包含 `{filename, page, content, relevance_score}` 等信息 |

---

## 4. 会话管理

### TC-CONV-001 — 创建会话

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/conversations`，body: `{"kb_id": "default", "title": "测试会话"}` | 返回 200，包含 `id`, `kb_id`, `title`, `message_count: 0`, `created_at`, `updated_at` |

### TC-CONV-002 — 创建会话时 kb_id 不存在（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/conversations`，body: `{"kb_id": "nonexistent"}` | 返回 404，error_code: `KB_NOT_FOUND` |

### TC-CONV-003 — 创建会话时 title 为空（使用默认值）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/conversations`，body: `{"kb_id": "default"}` (不传 title) | 正常创建，title 为空字符串，首次问答后自动设为 question[:30] |

### TC-CONV-004 — 创建会话 title 超长（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/conversations`，body: `{"kb_id": "default", "title": "（101 个字符）"}` | 返回 422 |

### TC-CONV-005 — 获取会话列表（分页）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 创建 25 个会话 | — |
| 2 | `GET /api/conversations?kb_id=default&page=1&page_size=20` | 返回 20 条，`total_count: 25` |
| 3 | `GET /api/conversations?kb_id=default&page=2&page_size=20` | 返回 5 条 |
| 4 | page=1, page_size=100 | 正常（最大值） |
| 5 | page=0 | 返回 422（page >= 1） |
| 6 | page_size=101 | 返回 422（page_size <= 100） |

### TC-CONV-006 — 获取会话详情（含消息）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GET /api/conversations/{conv_id}` | 返回 200，包含 `messages` 数组 |
| 2 | 传入不存在的 conv_id | 返回 404，error_code: `CONVERSATION_NOT_FOUND` |

### TC-CONV-007 — 更新会话标题

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `PATCH /api/conversations/{conv_id}`，body: `{"title": "新标题"}` | 返回 200，title 已更新 |

### TC-CONV-008 — 更新标题为空（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `PATCH /api/conversations/{conv_id}`，body: `{"title": ""}` | 返回 422（title 限制 1-100） |

### TC-CONV-009 — 删除会话

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `DELETE /api/conversations/{conv_id}` | 返回 200，`status: "deleted"` |
| 2 | 再次查询该会话 | 返回 404 |
| 3 | 该会话下的消息也被级联删除 | — |

### TC-CONV-010 — 自动标题生成

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 创建一个 title 为空的会话 | 成功 |
| 2 | 在该会话中提问 "Python 是什么？" | 回答后会话标题自动设置为 "Python 是什么？"[:30] |

### TC-CONV-011 — 消息计数正确

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 创建新会话 | `message_count: 0` |
| 2 | RAG 模式提问 1 次 | `message_count: 2`（1 user + 1 assistant） |
| 3 | 再提问 1 次 | `message_count: 4` |

### TC-CONV-012 — Agent 模式消息计数

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 模式提问，触发 1 次 tool_call | `message_count: 4`（1 user + 1 tool_call 标记 + 1 tool_result 标记 + 1 assistant） |
| 2 | Agent 模式提问，触发 2 次 tool_call | `message_count: 6` |

### TC-CONV-013 — 不同 kb_id 的会话隔离

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 在 KB-A 下创建会话 Conv-A，KB-B 下创建 Conv-B | — |
| 2 | `GET /api/conversations?kb_id=KB-A的id` | 只显示 Conv-A |
| 3 | `GET /api/conversations?kb_id=KB-B的id` | 只显示 Conv-B |

---

## 5. Agent

### TC-AG-001 — Agent 基本问答（知识库检索）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传文档到知识库 | 成功 |
| 2 | `POST /api/conversations/{conv_id}/agent`，body: `{"question": "（文档相关问题）"}` | 返回 200，agent 调用 search_knowledge_base 工具，回答基于文档内容 |

### TC-AG-002 — Agent 无需工具的问候（跳过工具调用）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/conversations/{conv_id}/agent`，body: `{"question": "你好"}` | 直接回复问候语，不调用任何工具，reasoning_steps 只有一条 answer 类型 |

### TC-AG-003 — Agent 知识库无结果（无 Tavily 时）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 不配置 Tavily API Key，上传文档 | — |
| 2 | 提问文档中不存在的内容 | Agent 先调用 search_knowledge_base，返回 "未找到相关文档。"，然后诚实地说明未找到并用自身知识回答 |

### TC-AG-004 — max_iterations 边界值

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `max_iterations: 1` | 正常 |
| 2 | `max_iterations: 10` | 正常 |
| 3 | `max_iterations: 0` | 返回 422 |
| 4 | `max_iterations: 11` | 返回 422 |

### TC-AG-005 — Agent 达到最大迭代次数

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `max_iterations: 1`，问一个需要多轮工具调用的问题 | 回答为 "抱歉，Agent 在最大迭代次数内未能完成推理。" |

### TC-AG-006 — Agent 流式输出（SSE）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `POST /api/conversations/{conv_id}/agent/stream`，提问文档相关内容 | SSE 事件顺序：`token`（流式文字）+ 可能的 `tool_call`/`tool_result` + `sources` + `done` |
| 2 | 验证 Content-Type | `text/event-stream` |
| 3 | 验证响应头 | 包含 `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no` |

### TC-AG-007 — Agent 流式 tool_call 事件格式

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 流式提问，触发工具调用 | 收到 `event: tool_call`，data 包含 `{"step": N, "tool": "search_knowledge_base", "args": "..."}` |
| 2 | 工具调用后 | 收到 `event: tool_result`，data 包含 `{"step": N, "tool": "search_knowledge_base", "found": N}` |

### TC-AG-008 — Agent 流式 done 事件

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 流式完成 | 最后一个事件为 `event: done`，data 包含 `{"conversation_id": "...", "message_id": N}` |

### TC-AG-009 — Agent 流式 LLM 调用失败（异常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 模拟 API Key 无效或网络不通（修改配置使 LLM 不可用） | 收到 `event: error`，data 包含 `{"message": "LLM 调用失败"}`，生成器正常退出不阻塞 |

### TC-AG-010 — Agent 空知识库

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 创建新 KB，不上传文档，创建会话 | — |
| 2 | Agent 提问 | 返回 "该知识库中还没有文档，请先上传 PDF。"（同 RAG 模式） |
| 3 | Agent 流式提问 | SSE 返回一条 token 事件后跟 done 事件 |

### TC-AG-011 — Agent 多次工具调用

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 配置 Tavily，上传文档 | — |
| 2 | 提问 "（文档中没有，但网上有的信息）" | Agent 先调用 search_knowledge_base（无结果），再调用 search_web（有结果），最终基于网络结果回答 |

### TC-AG-012 — Agent reasoning_steps 完整性

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 提问触发 1 次工具调用 | `reasoning_steps` 包含：`[{type: "tool_call"}, {type: "tool_result"}, {type: "answer"}]` |
| 2 | 验证 step 编号递增 | tool_call.step == tool_result.step，answer.step 更大 |

### TC-AG-013 — Agent source 去重

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 多次调用同一工具（如两次 search_knowledge_base 检索到相同 chunk） | 最终 sources 已去重，无重复条目 |

### TC-AG-014 — Agent 消息过滤（不泄露工具调用标记到 LLM）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 在同一会话中先 Agent 模式提问（触发工具调用），再切换到 RAG 模式提问 | RAG 模式的 `_build_messages` 不会包含 "[调用工具..." 或 "[工具返回..." 的消息 |

### TC-AG-015 — Agent 与 RAG 共享会话历史

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 会话中先用 RAG 提问 "你好" | 回复存入历史 |
| 2 | 同一会话中 Agent 提问 "我刚才说了什么？" | Agent 能引用历史中的上下文 |

### TC-AG-016 — 工具参数解析（query 键缺失时回退）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 观察 Agent 工具调用逻辑 | 若 tool_args 中无 "query" 键，回退到 "question" 键，再回退到原始问题文本 |

### TC-AG-017 — 工具参数 JSON 解析失败

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 模拟 LLM 返回非 JSON 的 tool_args | `_parse_tool_args` 返回空 dict，使用原始 question 作为查询词，不崩溃 |

### TC-AG-018 — 未知工具名称

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 模拟 LLM 调用一个不在 `_tool_handlers` 中的工具 | `_execute_tool` 返回 "未知工具: {tool_name}"，不崩溃 |

### TC-AG-019 — 非流式 Agent 的 question 参数校验

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | question 为空 | 返回 422 |
| 2 | question 超过 2000 字符 | 返回 422 |

### TC-AG-020 — Agent 流式断开后消息持久化

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 流式提问，中途客户端断开连接 | 注意：当前实现中，流断开后 `_finalize` 不会被调用，可能存在孤儿消息。记录当前行为供后续评估。 |

---

## 6. 联网搜索

### TC-WS-001 — 搜索网络（Tavily 已配置）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 在 `.env` 中配置 `TAVILY_API_KEY`，重启服务 | Agent 初始化时 `self._tavily_configured = True` |
| 2 | Agent 提问 "今天天气怎么样？" | Agent 调用 search_web 工具，返回基于网络搜索的回答 |

### TC-WS-002 — Tavily 未配置时的行为

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `.env` 中 `TAVILY_API_KEY` 为空或未设置 | Agent 只有 search_knowledge_base 一个工具 |
| 2 | 检查 system prompt | 不包含 search_web 的说明，只提到一个工具 |
| 3 | Agent 提问需要联网的问题 | Agent 只使用 search_knowledge_base，然后告知无法找到 |

### TC-WS-003 — 工具 schema 与 system prompt 一致性

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Tavily 已配置 | `self.tools` 包含 2 个工具，`self.system_prompt` 描述 2 个工具 |
| 2 | Tavily 未配置 | `self.tools` 包含 1 个工具，`self.system_prompt` 描述 1 个工具 |
| 3 | 验证无 "interpolation mismatch" | prompt 中提到的工具名与实际 tool schema 的 function.name 一致 |

### TC-WS-004 — search_web 返回空结果

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 调用 search_web，搜索一个无结果的关键词 | `_run_web_search` 返回 "未找到相关网络信息。"，Agent 如实告知用户 |

### TC-WS-005 — search_web 结果格式

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 调用 search_web | 返回的 source 包含 `{title, url, content, relevance_score}` 格式 |

### TC-WS-006 — WebSearchTool 初始化失败

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Tavily API Key 格式错误（如太短） | 初始化不报错，但实际搜索时 Tavily API 返回错误，`_run_web_search` 在外层 `_execute_tool` 中正常返回错误信息 |

### TC-WS-007 — search_web 的 max_results 参数

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 检查 WebSearchTool.search 调用 | 默认使用 `max_results=5`，可由 LLM 通过 tool_args 传入不同值 |

### TC-WS-008 — 知识库优先策略（先 KB 后 Web）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传包含某信息的文档，同时配置 Tavily | — |
| 2 | 提问文档中已覆盖的内容 | Agent 优先调用 search_knowledge_base，找到结果后不调用 search_web |
| 3 | 提问文档中没有的内容 | Agent 调用 search_knowledge_base（无结果），再调用 search_web |

### TC-WS-009 — 联网搜索超时/网络错误

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 模拟网络不通（断开外网）后 Agent 调用 search_web | 不崩溃，返回错误信息给 LLM，LLM 在回答中体现搜索失败 |

---

## 7. 来源展示

### TC-SRC-001 — RAG 模式 sources 结构

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | RAG 问答，检索到文档 | `sources` 数组中每项包含 `filename`, `page`, `content`, `relevance_score` |
| 2 | 验证 relevance_score | 值在 [0, 1] 范围内（由 `1.0 - cosine_distance` 计算） |

### TC-SRC-002 — Agent 模式 sources 结构

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 问答，调用 search_knowledge_base | `sources` 格式与 RAG 一致 |
| 2 | Agent 问答，同时调用 KB + Web | sources 合并两种来源，Web 来源包含 `url` 字段 |

### TC-SRC-003 — 前端来源面板展开/折叠

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 在聊天页面提问，获取到有来源的回答 | 助手消息下方显示 "📎 N 个来源" 可折叠面板 |
| 2 | 点击展开 | 显示每条来源的 filename、page、content 摘要、relevance_score |
| 3 | 再次点击折叠 | 来源列表隐藏 |

### TC-SRC-004 — 无来源时的展示

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 直接回复（无工具调用） | 助手消息不显示来源面板（或显示 "无来源"） |

### TC-SRC-005 — 来源去重展示

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 多次调用同一工具，检索到相同 chunk | 前端展示的来源列表无重复条目 |

### TC-SRC-006 — 来源页码正确

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传多页 PDF，提问涉及不同页面的内容 | 每条来源的 `page` 字段对应 PDF 中实际页码（近似值） |

### TC-SRC-007 — 来源文件名正确

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传文件 "我的测试文档.pdf" | sources 中 `filename` 为 "我的测试文档.pdf" |

### TC-SRC-008 — SSE 流式 sources 事件

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 流式提问 | 在 `done` 事件之前收到 `event: sources`，data 包含完整来源数组 |

---

## 8. Rerank

### TC-RR-001 — Rerank 开关（全局关闭）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 设置 `RERANK_ENABLED=false` | 检索不使用 Reranker，直接返回向量检索的 top_k 结果 |

### TC-RR-002 — Rerank 开关（接口级关闭）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `RERANK_ENABLED=true`，但请求中 `rerank: false` | 该次请求不重排 |

### TC-RR-003 — Rerank 正常流程

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `RERANK_ENABLED=true`，`rerank: true`，`retrieval_top_k: 0` | 先粗筛 `top_k * 3` 条，再用 Reranker 精排为 top_k 条 |
| 2 | 对比不重排的结果 | 重排后的结果相关性更高（相同查询下重排结果排序不同） |

### TC-RR-004 — Rerank 仅在结果多于 top_k 时触发

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 知识库中只有 2 条 chunk，`top_k: 4` | 不触发重排（检索结果 <= top_k），直接返回 2 条 |

### TC-RR-005 — Reranker 模型加载失败

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 设置无效的 `RERANKER_MODEL` 名称 | 启动时记录警告，`self._model = False`，`available` 属性返回 False，静默回退到无重排 |

### TC-RR-006 — Reranker compute_score 异常回退

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Reranker 可用但某次计算抛出异常 | 该次查询回退到原始检索顺序，记录警告日志，不崩溃 |

### TC-RR-007 — Reranker 单分数 vs 分数列表

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 传入单对 (question, document) 进行重排 | compute_score 可能返回 float（单值）而非 list；Reranker 正确处理两种情况 |

### TC-RR-008 — retrieval_top_k 手动指定

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `retrieval_top_k: 10`, `top_k: 4` | 先粗筛 10 条，再用 Reranker 精排为 4 条 |

### TC-RR-009 — Rerank 对最终答案质量的影响

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 上传内容丰富的文档，提问有明确答案的问题 | 开启重排时 answer 更精准、来源更相关 |

### TC-RR-010 — Rerank 不影响非检索场景

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Agent 模式中 search_knowledge_base 内部走 `retrieve_context` | Agent 也受益于 Rerank（如果开启） |
| 2 | search_web 调用 | 不经过 Rerank（Web 搜索有自己的排序逻辑） |

---

## 附录 A：综合场景测试

### TC-INT-001 — 端到端流程（上传→问答→会话→删除）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 创建知识库 "E2E测试" | 成功 |
| 2 | 上传 PDF | 成功 |
| 3 | 在 KB 下创建会话 | 成功 |
| 4 | RAG 提问 | 正常回答 + 来源 |
| 5 | Agent 提问 | 正常回答 + 推理步骤 |
| 6 | Agent 流式提问 | SSE 正常 |
| 7 | 删除会话 | 成功 |
| 8 | 删除文档 | 成功 |
| 9 | 删除知识库 | 成功 |

### TC-INT-002 — 多知识库并发

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 创建 3 个知识库，各上传不同文档 | — |
| 2 | 在每个 KB 下创建会话并提问 | 每个 KB 只检索到自己的文档，数据不混淆 |
| 3 | 同时上传文件到不同 KB | 无 ChromaDB 并发错误 |

### TC-INT-003 — 模式切换（RAG ↔ Agent）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 在同一会话中交替使用 RAG 和 Agent 模式提问 | 历史记录正常，模式切换不丢消息，Agent 工具标记不在 RAG 模式中泄露 |

### TC-INT-004 — 前端 UI 交互

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 访问 `/chat` | 页面正常渲染，知识库列表加载 |
| 2 | 切换知识库 | 会话列表更新 |
| 3 | 切换 RAG/Agent 模式 | 模式指示器更新 |
| 4 | 新建会话 | 会话出现在侧边栏 |
| 5 | Agent 流式提问 | "思考中..." 纯文字显示（无 HTML 标签），然后逐字显示回答，流式光标动画 |
| 6 | 回答完成后 | 文字停止闪烁，来源面板可展开 |
| 7 | 对话中发送多条消息 | 消息列表可滚动，新消息自动滚到底部 |
| 8 | Enter 发送 | 正常发送 |
| 9 | Shift+Enter 换行 | 输入框换行，不发送 |
| 10 | 上传弹窗 | 可拖放/点击选择，进度条显示 |

---

## 附录 B：健康检查与运维测试

### TC-OPS-001 — 健康检查（全部正常）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GET /health` | 返回 `{"status": "healthy", "chat_api": true, "embedding_api": true, "total_chunks": N}` |

### TC-OPS-002 — 健康检查（API 不可用）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 使用无效 API Key 启动 | `GET /health` 返回 `{"status": "degraded", "chat_api": false, ...}` |

### TC-OPS-003 — 启动时缺少 API Key

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `.env` 中 `DEEPSEEK_API_KEY` 为空或为 "your-deepseek-key" | 应用启动失败并退出 |

---

## 附录 C：测试用例统计

| 类别 | 用例数 | P0 相关 | P1 相关 |
|------|--------|---------|---------|
| 知识库管理 | 12 | — | — |
| 文档上传 | 17 | TC-UP-006, TC-UP-010 | TC-UP-008 |
| RAG 问答 | 14 | TC-RAG-006, TC-RAG-008 | — |
| 会话管理 | 13 | — | TC-CONV-012 |
| Agent | 20 | TC-AG-005, TC-AG-014, TC-AG-020 | TC-AG-020 |
| 联网搜索 | 9 | TC-WS-002, TC-WS-003 | — |
| 来源展示 | 8 | — | — |
| Rerank | 10 | — | TC-RR-005, TC-RR-006 |
| 综合场景 | 4 | TC-INT-002 | — |
| 运维 | 3 | — | — |
| **总计** | **110** | **8** | **6** |

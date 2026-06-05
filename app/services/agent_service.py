import json
import sys
import traceback

from openai import OpenAI

from app.config import settings
from app.repositories.conv_repo import ConvRepo
from app.repositories.msg_repo import MsgRepo
from app.services.kb_tool import KBTool, get_tool_schema as get_kb_tool_schema
from app.services.rag_pipeline import extract_summary, deduplicate_sources
from app.services.web_search_tool import (
    WebSearchTool,
    get_web_search_tool_schema,
)

_KB_ONLY_PROMPT = """\
You are an intelligent assistant with access to a knowledge base tool:

search_knowledge_base — search uploaded PDF/Word documents in the knowledge base.

Follow these rules:

1. ONLY skip tools for pure greetings (like "你好", "hi"), simple \
small talk, or questions completely unrelated to any factual content.
2. For facts, knowledge, concepts, data, definitions, or any question \
that the documents MIGHT answer, you MUST call search_knowledge_base first.
When in doubt, always search.
3. If the knowledge base finds no relevant information, honestly say so \
and then you may answer from your own knowledge.
4. Always reply in Chinese. Be concise.\
"""

_KB_WEB_PROMPT = """\
You are an intelligent assistant with access to two tools:
1. search_knowledge_base — search uploaded PDF/Word documents in the knowledge base
2. search_web — search the internet for latest information

Follow these rules:

1. ONLY skip tools for pure greetings (like "你好", "hi"), simple \
small talk, or questions completely unrelated to any factual content.
2. For facts, knowledge, concepts, data, definitions, or any question \
that the documents or internet MIGHT answer, you MUST call a tool first.
When in doubt, always search.
3. Try search_knowledge_base first for factual questions. If it finds no \
relevant information, or the question clearly needs latest/real-time info \
(like weather, news, current events, stock prices), use search_web.
4. Base your final answer on the tool results. If no tool finds relevant \
information, honestly say so and then you may answer from your own knowledge.
5. Always reply in Chinese. Be concise.\
"""

_KB_TOOL = get_kb_tool_schema()
_WEB_TOOL = get_web_search_tool_schema()


def _build_tools(tavily_configured: bool) -> list[dict]:
    if tavily_configured:
        return [_KB_TOOL, _WEB_TOOL]
    return [_KB_TOOL]


def _format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _parse_tool_args(tool_args: str) -> dict:
    try:
        return json.loads(tool_args)
    except (json.JSONDecodeError, TypeError):
        return {}


class AgentService:
    def __init__(self, vector_store, embedding_service, collection_name: str):
        self.kb_tool = KBTool(embedding_service, vector_store, collection_name)
        self.llm_client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        self.model = settings.chat_model
        self.conv_repo = ConvRepo()
        self.msg_repo = MsgRepo()

        self.web_search = None
        self._tavily_configured = bool(settings.tavily_api_key)
        if self._tavily_configured:
            self.web_search = WebSearchTool(settings.tavily_api_key)

        self.tools = _build_tools(self._tavily_configured)
        self.system_prompt = _KB_WEB_PROMPT if self._tavily_configured else _KB_ONLY_PROMPT

        # Tool registry: name → handler(query, top_k) → (result_text, sources)
        self._tool_handlers = {
            "search_knowledge_base": self._run_kb_search,
            "search_web": self._run_web_search,
        }

    # ── tool handlers ─────────────────────────────────────────

    def _run_kb_search(self, query: str, top_k: int) -> tuple[str, list[dict]]:
        context, sources = self.kb_tool.search(query, top_k)
        return context or "未找到相关文档。", sources

    def _run_web_search(self, query: str, _top_k: int) -> tuple[str, list[dict]]:
        if not self.web_search:
            return "联网搜索未配置（缺少 Tavily API Key）。", []
        context, sources = self.web_search.search(query)
        return context or "未找到相关网络信息。", sources

    def _execute_tool(self, tool_name: str, tool_args: str, question: str, top_k: int):
        args = _parse_tool_args(tool_args)
        query = args.get("query", args.get("question", question))

        handler = self._tool_handlers.get(tool_name)
        if handler:
            return handler(query, top_k)
        return f"未知工具: {tool_name}", []

    # ── shared helpers ────────────────────────────────────────

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

    def _save_tool_messages(self, conversation_id: str, tool_name: str, tool_args: str,
                            result_text: str):
        self.msg_repo.add(conversation_id, "assistant",
                          f"[调用工具: {tool_name}({tool_args[:200]})]")
        self.msg_repo.add(conversation_id, "tool",
                          f"[工具返回: {len(result_text)} 字符]")

    def _tc_id(self, tc) -> str:
        return tc["id"] if isinstance(tc, dict) else tc.id

    def _append_tool_messages(self, messages: list[dict], tc, tool_name: str,
                              tool_args: str, result_text: str):
        tc_id = self._tc_id(tc)
        messages.append({
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": tc_id, "type": "function",
                "function": {"name": tool_name, "arguments": tool_args},
            }],
        })
        messages.append({"role": "tool", "content": result_text, "tool_call_id": tc_id})

    def _finalize(self, conversation_id: str, final_answer: str, question: str,
                  unique_sources: list[dict], reasoning_steps: list[dict]) -> dict:
        from datetime import datetime, timezone
        from app.db.database import get_db

        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()
        sources_json = json.dumps(unique_sources, ensure_ascii=False) if unique_sources else None

        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, sources, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, "assistant", final_answer, sources_json, self.model, now),
        )
        msg_id = cursor.lastrowid

        tool_call_count = sum(1 for s in reasoning_steps if s["type"] == "tool_call")
        delta = 2 + 2 * tool_call_count
        conn.execute(
            "UPDATE conversations SET message_count = message_count + ?, updated_at = ? WHERE id = ?",
            (delta, now, conversation_id),
        )

        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row and not row["title"]:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (question[:30], now, conversation_id),
            )

        conn.commit()

        assistant_msg = self.msg_repo.get(msg_id)

        return {
            "conversation_id": conversation_id,
            "assistant_message": assistant_msg,
            "answer": final_answer,
            "summary": extract_summary(final_answer),
            "sources": unique_sources,
            "model_used": self.model,
            "reasoning_steps": reasoning_steps,
        }

    # ── ask (non-streaming) ───────────────────────────────────

    def ask(self, conversation_id: str, question: str, top_k: int = 4,
            temperature: float = 0.3, max_iterations: int = 5) -> dict:
        user_msg = self.msg_repo.add(conversation_id, "user", question)
        messages = self._build_messages(conversation_id, question)
        reasoning_steps, all_sources, final_answer = self._react_loop(
            messages, conversation_id, question, top_k, temperature, max_iterations, stream=False
        )
        result = self._finalize(conversation_id, final_answer, question,
                                deduplicate_sources(all_sources), reasoning_steps)
        result["user_message"] = user_msg
        return result

    # ── ask_stream (SSE) ──────────────────────────────────────

    def ask_stream(self, conversation_id: str, question: str, top_k: int = 4,
                   temperature: float = 0.3, max_iterations: int = 5):
        user_msg = self.msg_repo.add(conversation_id, "user", question)
        messages = self._build_messages(conversation_id, question)

        reasoning_steps: list[dict] = []
        all_sources: list[dict] = []
        final_answer = ""
        step = 0
        finalized = False

        try:
            for _ in range(max_iterations):
                step += 1
                try:
                    stream = self.llm_client.chat.completions.create(
                        model=self.model, messages=messages, tools=self.tools,
                        temperature=temperature, stream=True,
                    )
                except Exception:
                    print(f"[Agent Stream] LLM call failed:", file=sys.stderr)
                    traceback.print_exc()
                    yield _format_sse("error", {"message": "LLM 调用失败"})
                    return

                tool_deltas: dict[int, dict] = {}
                content_buf = ""
                finish_reason = None

                for chunk in stream:
                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_deltas:
                                tool_deltas[idx] = {
                                    "id": "", "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            d = tool_deltas[idx]
                            if tc.id:
                                d["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    d["function"]["name"] += tc.function.name
                                if tc.function.arguments:
                                    d["function"]["arguments"] += tc.function.arguments

                    if delta.content:
                        content_buf += delta.content
                        yield _format_sse("token", {"token": delta.content})

                if tool_deltas and finish_reason == "tool_calls":
                    for tc in (tool_deltas[i] for i in sorted(tool_deltas)):
                        tool_name = tc["function"]["name"]
                        tool_args = tc["function"]["arguments"]

                        reasoning_steps.append({
                            "step": step, "type": "tool_call",
                            "detail": f"调用 {tool_name}: {tool_args}",
                        })
                        yield _format_sse("tool_call", {
                            "step": step, "tool": tool_name, "args": tool_args[:200],
                        })

                        result_text, sources = self._execute_tool(tool_name, tool_args, question, top_k)
                        all_sources.extend(sources)

                        reasoning_steps.append({
                            "step": step, "type": "tool_result",
                            "detail": f"找到 {len(sources)} 条结果",
                        })
                        yield _format_sse("tool_result", {
                            "step": step, "tool": tool_name, "found": len(sources),
                        })

                        self._append_tool_messages(messages, tc, tool_name, tool_args, result_text)
                        self._save_tool_messages(conversation_id, tool_name, tool_args, result_text)
                else:
                    final_answer = content_buf
                    reasoning_steps.append({"step": step, "type": "answer", "detail": ""})
                    break

            if not final_answer:
                final_answer = "抱歉，Agent 在最大迭代次数内未能完成推理。"
                yield _format_sse("token", {"token": final_answer})

            unique_sources = deduplicate_sources(all_sources)
            yield _format_sse("sources", {"sources": unique_sources})

            result = self._finalize(conversation_id, final_answer, question,
                                    unique_sources, reasoning_steps)
            finalized = True
            yield _format_sse("done", {
                "conversation_id": conversation_id,
                "message_id": result["assistant_message"]["id"],
            })
        finally:
            if not finalized:
                try:
                    partial = final_answer or "（回答被中断）"
                    self.msg_repo.add(conversation_id, "assistant", partial, None, self.model)
                    tool_call_count = sum(1 for s in reasoning_steps if s["type"] == "tool_call")
                    self.conv_repo.increment_message_count(conversation_id, 2 + 2 * tool_call_count)
                except Exception:
                    pass

    # ── shared ReAct loop (non-streaming) ─────────────────────

    def _react_loop(self, messages, conversation_id, question, top_k, temperature,
                    max_iterations, stream=False):
        """Returns (reasoning_steps, all_sources, final_answer)."""
        reasoning_steps: list[dict] = []
        all_sources: list[dict] = []
        final_answer = ""
        step = 0

        for _ in range(max_iterations):
            step += 1
            try:
                response = self.llm_client.chat.completions.create(
                    model=self.model, messages=messages, tools=self.tools, temperature=temperature,
                )
            except Exception:
                print(f"[Agent] LLM call failed:", file=sys.stderr)
                traceback.print_exc()
                final_answer = "抱歉，AI 服务暂时不可用，请稍后重试。"
                break
            msg = response.choices[0].message

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    tool_args = tc.function.arguments

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
            else:
                final_answer = msg.content or ""
                reasoning_steps.append({"step": step, "type": "answer", "detail": ""})
                messages.append({"role": "assistant", "content": final_answer})
                break

        if not final_answer:
            final_answer = "抱歉，Agent 在最大迭代次数内未能完成推理。"
            print("[Agent] No final answer — max iterations reached", file=sys.stderr)

        return reasoning_steps, all_sources, final_answer

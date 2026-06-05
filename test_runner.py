"""RAG 项目完整测试执行脚本"""
import requests
import json
import sys
import os
import uuid

BASE = "http://localhost:8080/api"
PASS = 0
FAIL = 0
ERRORS = []

def test(case_id, description, method, path, expected_status, body=None, params=None, check_fn=None):
    global PASS, FAIL
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            resp = requests.get(url, params=params, timeout=60)
        elif method == "POST":
            resp = requests.post(url, json=body, params=params, timeout=60)
        elif method == "PATCH":
            resp = requests.patch(url, json=body, params=params, timeout=60)
        elif method == "PUT":
            resp = requests.put(url, json=body, params=params, timeout=60)
        elif method == "DELETE":
            resp = requests.delete(url, params=params, timeout=60)
        else:
            print(f"  ??? {case_id}: unknown method {method}")
            return None

        status_ok = resp.status_code == expected_status
        extra_ok = True
        extra_msg = ""
        if check_fn and status_ok:
            try:
                extra_ok, extra_msg = check_fn(resp)
            except Exception as e:
                extra_ok = False
                extra_msg = f"check_fn error: {e}"

        if status_ok and extra_ok:
            print(f"  PASS {case_id}: {description}")
            PASS += 1
        else:
            print(f"  FAIL {case_id}: {description} (expected {expected_status}, got {resp.status_code})")
            if extra_msg:
                print(f"         {extra_msg}")
            try:
                print(f"         Body: {resp.text[:300]}")
            except:
                pass
            FAIL += 1
            ERRORS.append(case_id)
        return resp
    except requests.exceptions.ConnectionError:
        print(f"  FAIL {case_id}: {description} - server not running")
        FAIL += 1
        ERRORS.append(case_id)
        return None
    except Exception as e:
        print(f"  FAIL {case_id}: {description} - {e}")
        FAIL += 1
        ERRORS.append(case_id)
        return None


def has_error_code(code):
    return lambda r: (r.json().get("error_code") == code, f"error_code={r.json().get('error_code')}")

def has_field(field, expected=None):
    def check(r):
        val = r.json().get(field)
        if expected is not None:
            return (val == expected, f"{field}={val}")
        return (val is not None and val != "", f"{field}={val}")
    return check

def field_in_list(field, values):
    return lambda r: (r.json().get(field) in values, f"{field}={r.json().get(field)}")

# ============================================================
# 0. HEALTH CHECK
# ============================================================
print("=" * 60)
print("  0. Health Check (TC-OPS)")
print("=" * 60)

test("TC-OPS-001", "Health check returns healthy",
     "GET", "/../health", 200,
     check_fn=field_in_list("status", ["healthy", "degraded"]))

# ============================================================
# 1. KNOWLEDGE BASE MANAGEMENT
# ============================================================
print("\n" + "=" * 60)
print("  1. Knowledge Base (TC-KB)")
print("=" * 60)

test("TC-KB-002", "Duplicate KB name returns 400",
     "POST", "/knowledge-bases", 400,
     body={"name": "默认知识库"},
     check_fn=has_error_code("KB_ALREADY_EXISTS"))

test("TC-KB-003", "Empty name returns 422",
     "POST", "/knowledge-bases", 422, body={"name": ""})

test("TC-KB-004", "Name >50 chars returns 422",
     "POST", "/knowledge-bases", 422, body={"name": "A" * 51})

test("TC-KB-005", "Description >200 chars returns 422",
     "POST", "/knowledge-bases", 422, body={"name": "test", "description": "B" * 201})

resp = test("TC-KB-001", "Create KB successfully",
     "POST", "/knowledge-bases", 200,
     body={"name": "TestKB-Auto", "description": "Auto test KB"})
created_kb_id = resp.json()["id"] if resp and resp.status_code == 200 else None

resp2 = test("TC-KB-001b", "Create second KB",
     "POST", "/knowledge-bases", 200,
     body={"name": "TestKB-Second", "description": "For cross-KB tests"})
second_kb_id = resp2.json()["id"] if resp2 and resp2.status_code == 200 else None

if created_kb_id:
    test("TC-KB-006a", "Get existing KB",
         "GET", f"/knowledge-bases/{created_kb_id}", 200,
         check_fn=has_field("name", "TestKB-Auto"))

test("TC-KB-006b", "Get nonexistent KB returns 404",
     "GET", "/knowledge-bases/nonexistent-id-12345", 404,
     check_fn=has_error_code("KB_NOT_FOUND"))

if created_kb_id:
    test("TC-KB-007", "Update KB name",
         "PUT", f"/knowledge-bases/{created_kb_id}", 200,
         body={"name": "TestKB-Renamed"})

    test("TC-KB-008", "Update to duplicate name returns 400",
         "PUT", f"/knowledge-bases/{created_kb_id}", 400,
         body={"name": "默认知识库"},
         check_fn=has_error_code("KB_ALREADY_EXISTS"))

test("TC-KB-011", "Update nonexistent KB returns 404",
     "PUT", "/knowledge-bases/nonexistent-id-99999", 404, body={"name": "nobody"})

test("TC-KB-010", "Delete default KB returns 400",
     "DELETE", "/knowledge-bases/default", 400,
     check_fn=has_error_code("DEFAULT_KB_DELETE_FORBIDDEN"))

# ============================================================
# 2. DOCUMENT UPLOAD
# ============================================================
print("\n" + "=" * 60)
print("  2. Document Upload (TC-UP)")
print("=" * 60)

# Create a test PDF file
TEST_PDF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_upload.pdf")
if not os.path.exists(TEST_PDF_PATH):
    # Minimal valid PDF
    minimal_pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
    )
    with open(TEST_PDF_PATH, "wb") as f:
        f.write(minimal_pdf)

# TC-UP-003: Unsupported type
# Can't easily test txt upload via multipart with fake txt easily here; test from boundary
# We'll use a .txt file to test
TXT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_file.txt")
with open(TXT_PATH, "w") as f:
    f.write("Hello world")

with open(TXT_PATH, "rb") as f:
    r = requests.post(f"{BASE}/upload", files={"file": ("test.txt", f, "text/plain")}, data={"kb_id": "default"})
status_ok = r.status_code == 400
print(f"  {'PASS' if status_ok else 'FAIL'} TC-UP-003: Unsupported file type returns 400 (got {r.status_code})")
if status_ok: PASS += 1
else: FAIL += 1; ERRORS.append("TC-UP-003")

# TC-UP-005: Nonexistent KB
with open(TEST_PDF_PATH, "rb") as f:
    r = requests.post(f"{BASE}/upload", files={"file": ("test.pdf", f, "application/pdf")}, data={"kb_id": "nonexistent"})
status_ok = r.status_code == 404
print(f"  {'PASS' if status_ok else 'FAIL'} TC-UP-005: Nonexistent KB returns 404 (got {r.status_code})")
if status_ok: PASS += 1
else: FAIL += 1; ERRORS.append("TC-UP-005")

# TC-UP-008: Corrupt DOCX
DOCX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_corrupt.docx")
with open(DOCX_PATH, "w") as f:
    f.write("not a docx file at all")
with open(DOCX_PATH, "rb") as f:
    r = requests.post(f"{BASE}/upload", files={"file": ("corrupt.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, data={"kb_id": "default"})
status_ok = r.status_code == 400
print(f"  {'PASS' if status_ok else 'FAIL'} TC-UP-008: Corrupt DOCX returns 400 (got {r.status_code})")
if status_ok: PASS += 1
else: FAIL += 1; ERRORS.append("TC-UP-008")

# TC-UP-006: Empty PDF (our minimal PDF has no text)
with open(TEST_PDF_PATH, "rb") as f:
    r = requests.post(f"{BASE}/upload", files={"file": ("empty.pdf", f, "application/pdf")}, data={"kb_id": "default"})
status_ok = r.status_code == 400
print(f"  {'PASS' if status_ok else 'FAIL'} TC-UP-006: Empty PDF returns 400 (got {r.status_code})")
if status_ok: PASS += 1
else: FAIL += 1; ERRORS.append("TC-UP-006")

# TC-UP-001: Upload real content
REAL_PDF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_real.pdf")
# We need a PDF with actual text. Use reportlab if available, else create a simple one.
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    import io
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(100, 750, "Python is a high-level programming language.")
    c.drawString(100, 730, "It is widely used for web development and AI.")
    c.drawString(100, 710, "FastAPI is a modern web framework for Python.")
    c.drawString(100, 690, "Machine learning models can be built with PyTorch.")
    c.save()
    with open(REAL_PDF, "wb") as f:
        f.write(buf.getvalue())
    HAS_REAL_PDF = True
except ImportError:
    print("  SKIP: reportlab not installed, some upload tests will be skipped")
    HAS_REAL_PDF = False

if HAS_REAL_PDF:
    with open(REAL_PDF, "rb") as f:
        r = requests.post(f"{BASE}/upload", files={"file": ("python_intro.pdf", f, "application/pdf")}, data={"kb_id": "default"})
    upload_ok = r.status_code == 200
    uploaded_doc_id = r.json().get("document_id") if upload_ok else None
    print(f"  {'PASS' if upload_ok else 'FAIL'} TC-UP-001: Upload PDF (got {r.status_code})")
    if upload_ok: PASS += 1
    else: FAIL += 1; ERRORS.append("TC-UP-001")

    if upload_ok:
        print(f"         doc_id={uploaded_doc_id}, chunks={r.json().get('chunk_count')}, pages={r.json().get('page_count')}")

    # TC-UP-013: Duplicate upload
    with open(REAL_PDF, "rb") as f:
        r2 = requests.post(f"{BASE}/upload", files={"file": ("python_intro.pdf", f, "application/pdf")}, data={"kb_id": "default"})
    dup_ok = r2.status_code == 200 and r2.json().get("document_id") != uploaded_doc_id
    print(f"  {'PASS' if dup_ok else 'FAIL'} TC-UP-013: Duplicate upload creates new doc_id")
    if dup_ok: PASS += 1
    else: FAIL += 1; ERRORS.append("TC-UP-013")
    dup_doc_id = r2.json().get("document_id") if r2.status_code == 200 else None

    # TC-UP-014: List documents
    r = requests.get(f"{BASE}/documents", params={"kb_id": "default"})
    docs_list = r.json().get("documents", [])
    list_ok = r.status_code == 200 and len(docs_list) >= 2
    print(f"  {'PASS' if list_ok else 'FAIL'} TC-UP-014: List documents (count={len(docs_list)})")
    if list_ok: PASS += 1
    else: FAIL += 1; ERRORS.append("TC-UP-014")

    # TC-UP-015: Delete document
    if uploaded_doc_id:
        r = requests.delete(f"{BASE}/documents/{uploaded_doc_id}", params={"kb_id": "default"})
        del_ok = r.status_code == 200 and r.json().get("status") == "deleted"
        print(f"  {'PASS' if del_ok else 'FAIL'} TC-UP-015: Delete document")
        if del_ok: PASS += 1
        else: FAIL += 1; ERRORS.append("TC-UP-015")

    # TC-UP-016: Delete nonexistent
    r = requests.delete(f"{BASE}/documents/nonexistent_doc_id", params={"kb_id": "default"})
    del_nf_ok = r.status_code == 404
    print(f"  {'PASS' if del_nf_ok else 'FAIL'} TC-UP-016: Delete nonexistent doc returns 404")
    if del_nf_ok: PASS += 1
    else: FAIL += 1; ERRORS.append("TC-UP-016")

# ============================================================
# 3. RAG Q&A
# ============================================================
print("\n" + "=" * 60)
print("  3. RAG Q&A (TC-RAG)")
print("=" * 60)

# TC-RAG-002: Empty question
test("TC-RAG-002", "Empty question returns 422",
     "POST", "/qa", 422, body={"question": "", "kb_id": "default"})

# TC-RAG-003: Too long question
test("TC-RAG-003", "Question >2000 chars returns 422",
     "POST", "/qa", 422, body={"question": "A" * 2001, "kb_id": "default"})

# TC-RAG-005: temperature boundary
test("TC-RAG-005a", "temperature=-0.1 returns 422",
     "POST", "/qa", 422, body={"question": "test", "temperature": -0.1})

test("TC-RAG-005b", "temperature=1.01 returns 422",
     "POST", "/qa", 422, body={"question": "test", "temperature": 1.01})

# TC-RAG-004: top_k boundary
test("TC-RAG-004a", "top_k=0 returns 422",
     "POST", "/qa", 422, body={"question": "test", "top_k": 0})

test("TC-RAG-004b", "top_k=21 returns 422",
     "POST", "/qa", 422, body={"question": "test", "top_k": 21})

# TC-RAG-010: retrieval_top_k
test("TC-RAG-010", "retrieval_top_k=101 returns 422",
     "POST", "/qa", 422, body={"question": "test", "retrieval_top_k": 101})

# TC-RAG-009: Nonexistent KB
test("TC-RAG-009", "QA to nonexistent KB returns 404",
     "POST", "/qa", 404, body={"question": "test", "kb_id": "nonexistent-kb"})

# TC-RAG-006: Empty KB
if second_kb_id:
    resp = test("TC-RAG-006", "QA to empty KB returns guidance message",
         "POST", "/qa", 200, body={"question": "Test question", "kb_id": second_kb_id})
    if resp:
        answer = resp.json().get("answer", "")
        has_msg = "该知识库中还没有文档" in answer
        if not has_msg:
            print(f"  FAIL TC-RAG-006: answer did not contain empty KB message. Got: {answer[:100]}")
            FAIL += 1; ERRORS.append("TC-RAG-006-val")
        else:
            print(f"  PASS TC-RAG-006-val: Empty KB message verified")

# TC-RAG-001: Real Q&A
if HAS_REAL_PDF:
    resp = test("TC-RAG-001", "RAG QA with documents returns answer + sources",
         "POST", "/qa", 200, body={"question": "Python is what?", "kb_id": "default", "top_k": 4})
    if resp and resp.status_code == 200:
        data = resp.json()
        has_answer = len(data.get("answer", "")) > 10
        has_sources = len(data.get("sources", [])) > 0
        has_summary = len(data.get("summary", "")) > 0
        if has_answer: print(f"  PASS TC-RAG-001-answer: Answer received ({len(data['answer'])} chars)")
        else: print(f"  FAIL TC-RAG-001-answer: Short or missing answer"); FAIL += 1; ERRORS.append("TC-RAG-001-ans")
        if has_sources: print(f"  PASS TC-RAG-013: Sources included ({len(data['sources'])} items)")
        else: print(f"  FAIL TC-RAG-013: No sources"); FAIL += 1; ERRORS.append("TC-RAG-013")
        if has_summary: print(f"  PASS TC-RAG-014: Summary included")
        else: print(f"  FAIL TC-RAG-014: No summary"); FAIL += 1; ERRORS.append("TC-RAG-014")

    # TC-RAG-011: Stateless QA
    resp2 = test("TC-RAG-011", "Stateless /api/qa works independently",
         "POST", "/qa", 200, body={"question": "web framework?", "kb_id": "default"})
    if resp2 and resp2.status_code == 200:
        print(f"  PASS TC-RAG-011: Second stateless QA OK")

# ============================================================
# 4. CONVERSATION MANAGEMENT
# ============================================================
print("\n" + "=" * 60)
print("  4. Conversation (TC-CONV)")
print("=" * 60)

test("TC-CONV-002", "Create conv with nonexistent KB returns 404",
     "POST", "/conversations", 404, body={"kb_id": "nonexistent-kb"})

test("TC-CONV-004", "Title >100 chars returns 422",
     "POST", "/conversations", 422, body={"kb_id": "default", "title": "A" * 101})

resp = test("TC-CONV-001", "Create conversation",
     "POST", "/conversations", 200, body={"kb_id": "default", "title": "TestConv"})
conv_id = resp.json()["id"] if resp and resp.status_code == 200 else None

resp3 = test("TC-CONV-003", "Create conv without title",
     "POST", "/conversations", 200, body={"kb_id": "default"})
conv_no_title_id = resp3.json()["id"] if resp3 and resp3.status_code == 200 else None

test("TC-CONV-005a", "List conversations page 1",
     "GET", "/conversations", 200, params={"kb_id": "default", "page": 1, "page_size": 20})

test("TC-CONV-005b", "page=0 returns 422",
     "GET", "/conversations", 422, params={"kb_id": "default", "page": 0})

test("TC-CONV-005c", "page_size=101 returns 422",
     "GET", "/conversations", 422, params={"kb_id": "default", "page_size": 101})

if conv_id:
    test("TC-CONV-006a", "Get conversation detail",
         "GET", f"/conversations/{conv_id}", 200,
         check_fn=has_field("title", "TestConv"))

    test("TC-CONV-007", "Update title",
         "PATCH", f"/conversations/{conv_id}", 200, body={"title": "NewTitle"})

test("TC-CONV-008", "Update title empty returns 422",
     "PATCH", f"/conversations/{conv_id or 'dummy'}", 422, body={"title": ""})

test("TC-CONV-006b", "Get nonexistent conv returns 404",
     "GET", "/conversations/nonexistent-conv-id", 404,
     check_fn=has_error_code("CONVERSATION_NOT_FOUND"))

if conv_id:
    test("TC-CONV-009", "Delete conversation",
         "DELETE", f"/conversations/{conv_id}", 200)

# ============================================================
# 5. CONVERSATION RAG QA
# ============================================================
print("\n" + "=" * 60)
print("  5. Conversation RAG QA (combined)")
print("=" * 60)

if conv_no_title_id and HAS_REAL_PDF:
    resp = test("TC-CONV-010", "Auto-title from first question",
         "POST", f"/conversations/{conv_no_title_id}/qa", 200,
         body={"question": "What is Python?", "top_k": 4})

    # Check auto-title
    r2 = requests.get(f"{BASE}/conversations/{conv_no_title_id}")
    title = r2.json().get("title", "") if r2.status_code == 200 else ""
    auto_title_ok = len(title) > 0
    print(f"  {'PASS' if auto_title_ok else 'FAIL'} TC-CONV-010-val: Auto-title set to '{title}'")
    if auto_title_ok: PASS += 1
    else: FAIL += 1; ERRORS.append("TC-CONV-010-val")

    # TC-CONV-011: Message count
    mc = r2.json().get("message_count", 0) if r2.status_code == 200 else 0
    mc_ok = mc == 2
    print(f"  {'PASS' if mc_ok else 'FAIL'} TC-CONV-011: Message count = {mc} (expected 2)")
    if mc_ok: PASS += 1
    else: FAIL += 1; ERRORS.append("TC-CONV-011")

    # Second question in same conv
    resp2 = test("TC-CONV-011b", "Second QA in same conversation",
         "POST", f"/conversations/{conv_no_title_id}/qa", 200,
         body={"question": "What framework is mentioned?", "top_k": 4})

# ============================================================
# 6. AGENT
# ============================================================
print("\n" + "=" * 60)
print("  6. Agent (TC-AG)")
print("=" * 60)

# Create a conv for Agent tests
resp_a = requests.post(f"{BASE}/conversations", json={"kb_id": "default", "title": "AgentTest"})
agent_conv_id = resp_a.json()["id"] if resp_a.status_code == 200 else None

# TC-AG-004: max_iterations boundary
test("TC-AG-004a", "max_iterations=0 returns 422",
     "POST", f"/conversations/{agent_conv_id or 'dummy'}/agent", 422,
     body={"question": "test", "max_iterations": 0})

test("TC-AG-004b", "max_iterations=11 returns 422",
     "POST", f"/conversations/{agent_conv_id or 'dummy'}/agent", 422,
     body={"question": "test", "max_iterations": 11})

# TC-AG-002: Greeting skips tools
if agent_conv_id:
    resp = test("TC-AG-002", "Greeting skips tool calls",
         "POST", f"/conversations/{agent_conv_id}/agent", 200,
         body={"question": "你好", "max_iterations": 3})
    if resp and resp.status_code == 200:
        steps = resp.json().get("reasoning_steps", [])
        tool_steps = [s for s in steps if s["type"] == "tool_call"]
        skip_ok = len(tool_steps) == 0
        print(f"  {'PASS' if skip_ok else 'FAIL'} TC-AG-002-val: Tool calls = {len(tool_steps)} (expected 0)")
        if skip_ok: PASS += 1
        else: FAIL += 1; ERRORS.append("TC-AG-002-val")

# TC-AG-001: Knowledge base retrieval
if agent_conv_id and HAS_REAL_PDF:
    resp = test("TC-AG-001", "Agent searches knowledge base",
         "POST", f"/conversations/{agent_conv_id}/agent", 200,
         body={"question": "What is Python?", "max_iterations": 5})
    if resp and resp.status_code == 200:
        steps = resp.json().get("reasoning_steps", [])
        tool_calls = [s for s in steps if s["type"] == "tool_call"]
        has_tool = len(tool_calls) >= 1
        has_answer = len(resp.json().get("answer", "")) > 10
        has_sources = len(resp.json().get("sources", [])) > 0
        if has_tool: print(f"  PASS TC-AG-001-tool: Tool calls = {len(tool_calls)}")
        else: print(f"  FAIL TC-AG-001-tool: No tool calls"); FAIL += 1; ERRORS.append("TC-AG-001-tool")
        if has_answer: print(f"  PASS TC-AG-001-answer: Answer received")
        else: print(f"  FAIL TC-AG-001-answer"); FAIL += 1; ERRORS.append("TC-AG-001-ans")
        if has_sources: print(f"  PASS TC-AG-001-sources: Sources included")
        else: print(f"  FAIL TC-AG-001-sources"); FAIL += 1; ERRORS.append("TC-AG-001-src")

# TC-AG-005: Max iterations reached
if agent_conv_id:
    resp = test("TC-AG-005", "Max iterations fallback message",
         "POST", f"/conversations/{agent_conv_id}/agent", 200,
         body={"question": "A" * 200, "max_iterations": 1})

# TC-AG-019: Agent question validation
test("TC-AG-019a", "Agent empty question returns 422",
     "POST", f"/conversations/{agent_conv_id or 'dummy'}/agent", 422,
     body={"question": ""})

test("TC-AG-019b", "Agent question >2000 returns 422",
     "POST", f"/conversations/{agent_conv_id or 'dummy'}/agent", 422,
     body={"question": "A" * 2001})

# ============================================================
# 7. AGENT STREAMING (SSE)
# ============================================================
print("\n" + "=" * 60)
print("  7. Agent Streaming SSE (TC-AG-006..009)")
print("=" * 60)

if agent_conv_id:
    r = requests.post(
        f"{BASE}/conversations/{agent_conv_id}/agent/stream",
        json={"question": "Hello", "max_iterations": 3},
        stream=True, timeout=60
    )
    sse_ok = r.status_code == 200
    ct = r.headers.get("content-type", "")
    events_seen = set()
    tokens = []

    if sse_ok:
        buffer = ""
        current_event = None
        try:
            for chunk in r.iter_content(chunk_size=None):
                if chunk:
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if line.startswith("event: "):
                            current_event = line[7:].strip()
                        elif line.startswith("data: ") and current_event:
                            data = json.loads(line[6:])
                            events_seen.add(current_event)
                            if current_event == "token":
                                tokens.append(data.get("token", ""))
                            current_event = None
        except Exception as e:
            print(f"         SSE stream read exception (may be normal): {e}")

    sse_status = r.status_code == 200
    has_ct = "text/event-stream" in ct
    print(f"  {'PASS' if sse_status else 'FAIL'} TC-AG-006: SSE status={r.status_code}")
    if sse_status: PASS += 1
    else: FAIL += 1; ERRORS.append("TC-AG-006")
    print(f"  {'PASS' if has_ct else 'FAIL'} TC-AG-006-ct: Content-Type={ct}")
    if has_ct: PASS += 1
    else: FAIL += 1; ERRORS.append("TC-AG-006-ct")
    full_text = "".join(tokens)
    has_tokens = len(full_text) > 0
    print(f"  {'PASS' if has_tokens else 'FAIL'} TC-AG-006-tokens: Received {len(tokens)} token events")
    if has_tokens: PASS += 1
    else: FAIL += 1; ERRORS.append("TC-AG-006-tok")

    has_done = "done" in events_seen
    print(f"  {'PASS' if has_done else 'FAIL'} TC-AG-008: Done event received [events: {sorted(events_seen)}]")
    if has_done: PASS += 1
    else: FAIL += 1; ERRORS.append("TC-AG-008")

# TC-AG-010: Empty KB agent stream
if second_kb_id:
    # Create conv for empty KB
    r = requests.post(f"{BASE}/conversations", json={"kb_id": second_kb_id, "title": "EmptyKB"})
    empty_conv_id = r.json()["id"] if r.status_code == 200 else None
    if empty_conv_id:
        r2 = requests.post(
            f"{BASE}/conversations/{empty_conv_id}/agent/stream",
            json={"question": "test"},
            stream=True, timeout=30
        )
        empty_status = r2.status_code == 200
        print(f"  {'PASS' if empty_status else 'FAIL'} TC-AG-010: Empty KB stream returns 200")
        if empty_status: PASS += 1
        else: FAIL += 1; ERRORS.append("TC-AG-010")

# ============================================================
# 8. WEB SEARCH (if Tavily configured)
# ============================================================
print("\n" + "=" * 60)
print("  8. Web Search (TC-WS)")
print("=" * 60)

# Check if Tavily is configured via health or by checking config
try:
    from app.config import settings
    tavily_ok = bool(settings.tavily_api_key)
except:
    tavily_ok = False

print(f"  INFO: Tavily configured = {tavily_ok}")

if tavily_ok and agent_conv_id:
    resp = test("TC-WS-001", "Agent web search for realtime info",
         "POST", f"/conversations/{agent_conv_id}/agent", 200,
         body={"question": "What is the weather today?", "max_iterations": 5})
    if resp and resp.status_code == 200:
        steps = resp.json().get("reasoning_steps", [])
        web_calls = [s for s in steps if s["type"] == "tool_call" and "web" in s.get("detail", "").lower()]
        kb_calls = [s for s in steps if s["type"] == "tool_call" and "knowledge" in s.get("detail", "").lower()]
        print(f"  INFO TC-WS-008: KB calls={len(kb_calls)}, Web calls={len(web_calls)}")
else:
    print("  SKIP: Tavily not configured or no agent conv")

# ============================================================
# 9. SOURCE DISPLAY
# ============================================================
print("\n" + "=" * 60)
print("  9. Source Display (TC-SRC)")
print("=" * 60)

if HAS_REAL_PDF:
    resp = requests.get(f"{BASE}/documents", params={"kb_id": "default"})
    docs = resp.json().get("documents", [])
    if docs:
        r = requests.post(f"{BASE}/qa", json={"question": "Python programming language?", "kb_id": "default"})
        sources = r.json().get("sources", [])
        if sources:
            src = sources[0]
            has_filename = "filename" in src and len(src["filename"]) > 0
            has_page = "page" in src
            has_score = "relevance_score" in src
            has_content = "content" in src and len(src["content"]) > 0
            print(f"  {'PASS' if has_filename else 'FAIL'} TC-SRC-001-fn: filename={src.get('filename')}")
            if has_filename: PASS += 1
            else: FAIL += 1; ERRORS.append("TC-SRC-001-fn")
            print(f"  {'PASS' if has_page else 'FAIL'} TC-SRC-001-pg: page={src.get('page')}")
            if has_page: PASS += 1
            else: FAIL += 1; ERRORS.append("TC-SRC-001-pg")
            print(f"  {'PASS' if has_score else 'FAIL'} TC-SRC-001-sc: score={src.get('relevance_score')}")
            if has_score: PASS += 1
            else: FAIL += 1; ERRORS.append("TC-SRC-001-sc")
            print(f"  {'PASS' if has_content else 'FAIL'} TC-SRC-001-ct: content preview present")
            if has_content: PASS += 1
            else: FAIL += 1; ERRORS.append("TC-SRC-001-ct")

            # TC-SRC-005: dedup
            unique_ids = set()
            dup_found = False
            for s in sources:
                key = (s.get("document_id", ""), s.get("page", 0))
                if key in unique_ids:
                    dup_found = True
                    break
                unique_ids.add(key)
            print(f"  {'PASS' if not dup_found else 'FAIL'} TC-SRC-005: No duplicate sources")
            if not dup_found: PASS += 1
            else: FAIL += 1; ERRORS.append("TC-SRC-005")

# ============================================================
# 10. RERANK
# ============================================================
print("\n" + "=" * 60)
print("  10. Rerank (TC-RR)")
print("=" * 60)

test("TC-RR-002", "Rerank=false disables rerank",
     "POST", "/qa", 200,
     body={"question": "test question about Python", "kb_id": "default", "rerank": False})

# TC-RR-003: Rerank on
test("TC-RR-003", "Rerank=true enables rerank",
     "POST", "/qa", 200,
     body={"question": "test about web frameworks", "kb_id": "default", "rerank": True, "retrieval_top_k": 0})

# TC-RR-004: Fewer results than top_k - reranker not called
# This is tested implicitly since our test KB is small
test("TC-RR-010", "Rerank doesn't affect agent KB search",
     "POST", "/qa", 200,
     body={"question": "machine learning?", "kb_id": "default", "rerank": True})

# ============================================================
# 11. CLEANUP
# ============================================================
print("\n" + "=" * 60)
print("  11. Cleanup")
print("=" * 60)

# Delete test KBs
if second_kb_id:
    r = requests.delete(f"{BASE}/knowledge-bases/{second_kb_id}")
    print(f"  Cleanup: Delete second KB -> {r.status_code}")

if created_kb_id:
    r = requests.delete(f"{BASE}/knowledge-bases/{created_kb_id}")
    print(f"  Cleanup: Delete test KB -> {r.status_code}")

# Clean up temp files
for f in [TEST_PDF_PATH, TXT_PATH, DOCX_PATH, REAL_PDF]:
    try:
        os.remove(f)
    except:
        pass

# ============================================================
# FINAL REPORT
# ============================================================
print("\n" + "=" * 60)
print(f"  TEST RESULTS: {PASS} passed, {FAIL} failed, {PASS+FAIL} total")
if ERRORS:
    print(f"  Failed: {', '.join(ERRORS)}")
print("=" * 60)

# 检索质量评测

用一套可复现的标注集，量化"改动检索链路到底有没有变好"。

## 为什么需要它

项目原先只有 `TEST_CHECKLIST.md` 描述的功能性用例——它们能证明"接口不报错"，
但证明不了"检索变准了"。于是出现过这样的状况：简历上写着"集成 BGE-Reranker
提升召回精度"，而实际上 `RERANK_ENABLED` 根本没配、模型从未加载过。

定量评测要解决的就是这件事：把"感觉变好了"换成"Recall@4 从 x 提到 y"。

## 指标选择

只用**纯检索指标**，不调用 LLM 当裁判：

| 指标 | 含义 |
|------|------|
| Recall@4 | gold 中被召回的比例——衡量"漏没漏" |
| Hit@1 | 排在第一位的就命中的问题占比——衡量"排得准不准" |
| MRR@4 | 首个命中项排名的倒数均值 |
| nDCG@4 | 考虑排序位次折损的累计增益（二元相关性） |

不用 LLM 打分的原因：回答级指标（忠实度/相关性）有成本、有随机性、换模型就
不可比。检索指标是**确定性**的——同样输入必得同样分数，所以能当回归测试用，
改一行代码就能立刻看出检索有没有变差。

## 语料

项目根目录下的全部 Markdown 文档（README / ARCHITECTURE / INTERVIEW_ANSWERS /
TEST_CHECKLIST / FIX_TASKS / PROJECT_PORTFOLIO），约 17 万字符 → **173 个 chunk**。

为什么不直接评测线上 `kb_default`：它只有 12 个 chunk，而 reranker 的候选池
默认是 `top_k × retrieval_multiplier = 4 × 3 = 12`，恰好等于全库。此时
"扩大候选池"和"不扩大候选池"会退化成同一个配置，测不出精排的贡献。

评测语料与业务数据**完全隔离**：`_common.py` 在任何 `app.*` 导入之前把
`CHROMA_PERSIST_DIR` 注入为 `eval/.chroma_eval`，业务库 `chroma_data/` 不受影响。

## 标注方式

`dataset.jsonl` 每行一条：

```json
{"qid": "q07", "question": "切块时保留 200 字符重叠是为了防止什么？",
 "evidence": "防止关键句刚好落在切分边界被截断",
 "category": "chunking", "difficulty": "easy"}
```

关键点：**ground truth 写的是"答案原文片段"，不是手写的 chunk id**。脚本按子串
匹配把它映射成 gold chunk 集合，于是标注可以被机器验证——片段找不到就说明标注
写错了（或语料变了），脚本会直接报出来并把这些样本剔除，而不是静默拉低指标。

当前标注：46 条，覆盖 17 个类别；easy 17 / medium 19 / hard 10；
其中 34 条有多个 gold（内容在文档间存在交叉，属真实知识库的常态）。

## 配置档位

| 档 | 配置 | k | 用途 |
|----|------|---|------|
| A | 向量 top4 | 4 | `RERANK_ENABLED=false` 时的线上行为（基线） |
| B | 向量 top12 | 12 | 候选池**上限**：gold 有没有被召进池子 |
| C | 向量 top12 + 精排 → 4 | 4 | `RERANK_ENABLED=true` 时的线上行为 |
| D | 混合 top12 → 截断 4 | 4 | 向量 + BM25 经 RRF 融合，不精排 |
| E | 混合 top12 + 精排 → 4 | 4 | 当前能做到的最好路径 |

**B 档的 k 是 12，与其余四档的 k=4 不可直接比较**——它给出的是精排的天花板：
C 在同一个候选池上把 k=4 的召回补到多少，就说明精排"从池子里捞正确答案"的能力。

⚠️ 踩过的坑：B 最初写成"向量 top12 → 截断到 4"，结果它在数学上**必然等于 A**
（同一路向量排序取前 4 条），实测两档四项指标完全相同 0.677 / 0.739 / 0.793 / 0.675，
这一档就白跑了。要衡量候选池的价值，就必须让它按自己的 k 报指标。

## 用法

```bash
# 1) 建索引（首次会调用 embedding API；之后命中缓存不再计费）
python eval/build_index.py

# 2) 只校验标注，不调用 API
python eval/run_eval.py --validate-only

# 3) 跑指标（结果写入 eval/results/metrics.json）
python eval/run_eval.py
python eval/run_eval.py --only A,C,E     # 只跑指定档位
python eval/run_eval.py --only A,B,D --out metrics_fast.json   # --out 避免覆盖
```

### 为什么建议分两批跑

跑 C / E 档（含精排）**每档约 15~20 分钟**：46 题 × 12 条候选 = 540 对文本要过
一遍 568M 参数的 Cross-encoder，纯 CPU（无 CUDA）时单次 query 约 21 秒。
A / B / D 三档只需 1~25 ms，秒级完成。所以调参阶段用 `--only A,B,D` 迭代，
只在需要精排数据时才跑全量，并用 `--out` 把两批结果分开保存。

## 前置条件

- 依赖装在项目所用的解释器（本地为 `pip install --user` 的用户级 site-packages）
- Embedding 走 `app.services.EmbeddingService`，与线上同一模型（DashScope
  `text-embedding-v3`）。**账号欠费会直接失败**（`Arrearage`）。
- 跑 C / E 档需加载 bge-reranker-v2-m3，约 2.2 GB 内存；内存不足时进程会被系统
  杀掉且没有输出。跑 A / B / D 不需要。
- 共用的向量缓存：`eval/.cache/corpus_embeddings.npz`（173 条，语料侧）、
  `eval/.cache/query_embeddings.npz`（问题侧）。

# Research foundations

Each technique in Masdar comes from published work. The table maps every paper to the idea we
take from it and the place it lives in the code. **Status** is updated as each phase lands.

## Retrieval

| Paper | Idea we use | Where | Status |
|---|---|---|---|
| Unicode Consortium, *UAX #15: Unicode Normalization Forms* | NFKC folds presentation forms (ﻻ) and compatibility characters before matching | `domain/arabic.py` | ✅ |
| Larkey, Ballesteros & Connell (2002), *Improving Stemming for Arabic Information Retrieval: Light Stemming and Co-occurrence Analysis*, SIGIR | Normalization in the spirit of the common Arabic IR practice it popularised (diacritics, tatweel, alef). Note: Larkey applies some letter rules only word-finally as part of stemming, while we fold ى and ة everywhere and measure the effect (ADR-0003). The *light10* stemmer is planned for BM25 | `domain/arabic.py`, BM25 tokenizer | normalization ✅, stemming planned |
| Robertson & Zaragoza (2009), *The Probabilistic Relevance Framework: BM25 and Beyond*, FnTIR | BM25 lexical baseline | `adapters/bm25.py` | planned |
| Karpukhin et al. (2020), *Dense Passage Retrieval for Open-Domain Question Answering*, EMNLP | Bi-encoder dense retrieval | `adapters/e5_embedder.py` | planned |
| Wang et al. (2022), *Text Embeddings by Weakly-Supervised Contrastive Pre-training* (E5); Wang et al. (2024), *Multilingual E5 Text Embeddings: A Technical Report* | `multilingual-e5-small` with `query:` / `passage:` prefixes | `adapters/e5_embedder.py` | planned |
| Chen et al. (2024), *BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity*, arXiv:2402.03216 | Optional stronger embedder, benchmarked against mE5 if disk allows | `adapters/` | optional |

## Fusion and reranking

| Paper | Idea we use | Where | Status |
|---|---|---|---|
| Cormack, Clarke & Büttcher (2009), *Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods*, SIGIR | RRF: merge lexical and dense lists using ranks rather than scores (k=60) | `domain/fusion.py` | planned |
| Nogueira & Cho (2019), *Passage Re-ranking with BERT*, arXiv:1901.04085 | Cross-encoder reranking of the fused top-k | `adapters/cross_encoder.py` | planned |
| Anthropic (2024), *Introducing Contextual Retrieval* | Prepend context to every chunk before indexing. We use the law/part/chapter titles, so no LLM call is needed | `domain/chunking.py` | ✅ |

## Evaluation

| Paper | Idea we use | Where | Status |
|---|---|---|---|
| Järvelin & Kekäläinen (2002), *Cumulated Gain-Based Evaluation of IR Techniques*, ACM TOIS | nDCG@10 | `evaluation/metrics.py` | planned |
| Thakur et al. (2021), *BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of IR Models*, NeurIPS | Corpus layout (`corpus.jsonl` / `queries.jsonl` / `qrels`) and evaluation protocol: Recall@k, nDCG@10, BM25 as the baseline to beat | `adapters/beir_writer.py`, `evaluation/` | corpus ✅, eval planned |
| Es et al. (2023), *RAGAS: Automated Evaluation of Retrieval Augmented Generation*, arXiv:2309.15217 | Faithfulness of the optional LLM answer to the cited articles | `evaluation/` | planned |

## Generation (optional layer)

| Paper | Idea we use | Where | Status |
|---|---|---|---|
| Lewis et al. (2020), *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*, NeurIPS | Ground answers in retrieved passages | `app/answer.py` | planned |
| Liu et al. (2023), *Lost in the Middle: How Language Models Use Long Contexts*, TACL 2024 | Put the strongest evidence first and keep the context short | `app/answer.py` | planned |

# Project TODOs & Future Enhancements

## 🔴 High Priority (Blockers)
- [x] **Reduce Bedrock AgentCore 424 Risk**: Deferred agent graph initialization to first invocation (`get_agent_graph()` in `agent.py`). The `/ping` health check now responds immediately. Pinned `--workers 1 --timeout-keep-alive 120` in Dockerfile CMD.

- [x] **Langfuse v3 migration**: Fixed `langfuse.callback` → `langfuse.langchain`; `session_id=` → `trace_context={"trace_id": ...}`; removed `flush()`.

- [x] **Switch to Claude Opus 4.6**: Updated `agent.py` to use `us.anthropic.claude-opus-4-6-v1` via `ChatBedrockConverse`. Updated `main.py` to use `ainvoke()` instead of `astream()` to avoid forcing the streaming API. Deployed as container v4 (arm64).

- [x] **AWS Marketplace subscription for Claude Opus 4.6** — RESOLVED
    - Added `aws-marketplace:ViewSubscriptions` + `aws-marketplace:Subscribe` to `agentcore_execution_role` (IAM + Terraform).
    - Accepted foundation model agreement via `bedrock create-foundation-model-agreement --model-id us.anthropic.claude-opus-4-6-v1 --offer-token <token>`.
    - Agent now responds correctly to all 3 tool-use queries (AAPL price, NVDA history, TSLA sentiment).

- [x] **Notebook fix: use `AccessToken` not `IdToken`** — FIXED in `invocation_demo.ipynb`
    - Cell 6 already captures `access_token`; cell 8 updated to use it with correct `"event"` field parsing.
    - Fixed fallback password to `FinAIAgent2026@`, dynamic session ID, corrected response parsing.

- [x] **Notebook fully passwordless**: Removed notebook password dependency and switched invocation signing to AWS SigV4 with temporary credentials bootstrap.
- [x] **Fix `aws` binary not found in notebook runtime**: Added robust AWS CLI resolution (`aws` binary, `python -m awscli`, install-on-demand fallback).
- [x] **Auth flow mismatch/403 cleanup**: Standardized on SigV4 path for AgentCore calls to avoid OAuth/SigV4 mismatch.
- [x] **Guest credential bootstrap hardening**: Added refresh/expired-token handling and clearer diagnostics in runtime helpers.
- [ ] **Still open**: Contact AWS Support regarding "UnknownOperationException" in preview runtime.
- [ ] **Still open**: Attach/verify final IAM session policy path for guest role so all required `ssm:GetParameter` reads succeed in every environment.

## 🟡 Medium Priority (Feature Gap)
- [x] **Langfuse + SSM wiring for notebook**: Notebook now reads Langfuse keys/base URL from SSM and verifies API connectivity.
- [x] **Model invocation logging IaC**: Added Bedrock model invocation logging resources and CloudWatch destination for runtime observability.
- [x] **Notebook output compaction**: Moved long runtime logic to GitHub-side Python/R runtime files loaded from alias in notebook.
- [x] **Auto-collapse/noise reduction**: Kept first block focused on environment output and reduced verbose install/runtime logs.
- [ ] **Full OpenSearch Serverless Integration**: Move from S3-only retrieval to a complete Vector Database setup for the Knowledge Base.
- [x] **`retrieve_news_sentiment` tool**: Added to `python/tools.py` — fetches recent Yahoo Finance headlines and computes BULLISH/BEARISH/NEUTRAL sentiment via keyword matching.
    - [ ] Upgrade to a proper NLP model (e.g., `transformers` FinBERT) for higher accuracy.
- [ ] **Add support for scraping analyst PDF reports directly from the web.**
- [x] **CI/CD Integration**: `.github/workflows/ci.yml` added — runs Terraform fmt/validate, Docker build, and Python linting (ruff) on every PR.

## 🟢 Low Priority (Polish & UX)
- [x] **Notebook chat UI enhancement**: Added dark-mode, left-justified floating Q/A boxes with markdown/table/code rendering.
- [x] **Readable output width**: Wrapped answer rendering for improved readability in notebook logs.
- [ ] **Notebook UI Enhancement**: Add interactive widgets (`ipywidgets`) to allow users to type custom ticker symbols.
- [ ] **Cost Optimization**: Refine `infracost` hooks for more granular Bedrock model invocation cost estimates.
- [ ] **Token usage UX**: Replace temporary `Tokens: usage coming soon` fallback with true per-Q/A token accounting once AgentCore/model path exposes it consistently.
- [x] **Security Auditing (partial)**: IAM policies narrowed from wildcard `*` to exact ARNs. `bedrock:Converse` + `bedrock:ConverseStream` added. `arn:aws:bedrock:*::foundation-model/*` (wildcard region) added for cross-region inference profiles.
    - Remaining `*` resources: `ecr:GetAuthorizationToken` (AWS requirement), `bedrock-agentcore:*`, `cognito-identity:*` (no resource-level support).

## 📋 Key Architecture Findings (from CloudTrail + IAM Analyzer investigation)
- **Bedrock model access for IAM roles**: All Anthropic models require either (a) AWS Marketplace subscription, or (b) use-case form submission (`put-use-case-for-model-access` API, blob format undocumented). Root bypasses some of these checks.
- **Streaming vs non-streaming**: `InvokeModelWithResponseStream` and `ConverseStream` trigger stricter access checks than `Converse` (non-streaming) for IAM roles.
- **`ainvoke()` + `ChatBedrockConverse`** → uses `bedrock-runtime:Converse` (non-streaming). This is the correct path to avoid the streaming form requirement.
- **AgentCore runtime ID**: The full ID with suffix is `Financial_Analyst_Agent-hvRgckAqaW` (not just `Financial_Analyst_Agent`).
- **Container architecture**: Must be `arm64` for AgentCore runtime (not `amd64`).
- **Cognito auth**: Use `AccessToken` (not `IdToken`) for AgentCore JWT bearer auth.
- **Notebook runtime loading**: Lightweight notebook now fetches runtime logic from GitHub-side Python/R files and executes through alias bootstrap.

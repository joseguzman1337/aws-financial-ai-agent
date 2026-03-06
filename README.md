# AWS Financial AI Agent - Secure IaC & Containerized Deployment

A production-ready, serverless financial AI agent built with **FastAPI**, **LangGraph**, and **AWS Bedrock AgentCore**, featuring a rigorous automated security and linting pipeline.

---

## 🛠 Project Milestones (Session History)

<details>
<summary><b>1. Infrastructure Foundation (Terraform)</b></summary>

- **Base Resources:** Provisioned Cognito User Pools, S3 Buckets, ECR Repositories, and IAM Roles.
- **Provider Pinning:** Locked AWS and Random providers to latest stable versions.
</details>

<details>
<summary><b>2. Containerization (Python 3.13)</b></summary>

- **Modern Stack:** Upgraded base image to `python:3.13-slim`.
- **Security Hardening:** Implemented non-root user (`appuser`), pinned `pip` version, and added container `HEALTHCHECK`.
- **ARM64 Native Builds:** Leveraged **Colima** to build and push native `linux/arm64` images to AWS ECR.
</details>

<details>
<summary><b>3. Automated Security Pipeline (Husky & Pre-commit)</b></summary>

- **Comprehensive Scanning:** Integrated 8+ industry-standard tools:
  - **Checkov/Terrascan/KICS:** Static Analysis for IaC.
  - **TFLint:** Terraform linting and best practices.
  - **Trivy/Grype:** Container and dependency vulnerability scanning.
  - **Snyk:** Application-level security analysis.
  - **Infracost:** Real-time cloud cost estimates on commit.
- **Execution Strategy:** Optimized hooks to run individually to prevent resource contention and hangs.
</details>

<details>
<summary><b>4. Secrets Management (AWS KMS & SSM)</b></summary>

- **Encrypted Storage:** Configured AWS SSM Parameter Store with `SecureString` types.
- **KMS Integration:** Created a dedicated KMS Key for encrypting application secrets (Langfuse, Snyk, Infracost).
- **IAM Least Privilege:** Tightened agent execution policies to allow only specific `kms:Decrypt` and `ssm:GetParameter` actions on defined model/parameter ARNs.
</details>

<details>
<summary><b>5. Code Quality & Formatting</b></summary>

- **Pylint Excellence:** Refactored code to achieve a perfect **10.00/10** Pylint score.
- **Strict Formatting:** Applied **Black** (79-char limit), **Isort**, and **Ruff** for consistent, idiomatic Python.
- **Documentation:** Added module-level docstrings and type hints across `main.py`, `agent.py`, and `tools.py`.
</details>

<details>
<summary><b>6. IaC Security Hardening</b></summary>

- **S3 Best Practices:** Enabled **Versioning** and **Server Access Logging** for all buckets.
- **ECR Security:** Configured **KMS Encryption**, **Scan-on-Push**, and **Image Tag Immutability**.
- **IAM Compliance:** Resolved "Data Exfiltration" findings by moving from broad `*` actions to specific resource ARNs.
- **Access Analyzer:** Deployed AWS Access Analyzer to continuously monitor resource permissions.
</details>

---

## 🚀 Getting Started

<details>
<summary><b>Prerequisites</b></summary>

- **AWS CLI:** Configured with profile `t1cx`.
- **Docker/Colima:** For ARM64 builds.
- **Terraform:** v1.14.6+.
- **Node.js/NPM:** For Husky hooks.
</details>

<details>
<summary><b>Installation & Deployment</b></summary>

1. **Setup Hooks:**
   ```bash
   npm install
   pre-commit install
   ```
2. **Build & Push Image:**
   ```bash
   colima start --arch aarch64
   # Build from root using docker/Dockerfile
   docker build -t <ECR_URI>:latest -f docker/Dockerfile .
   docker push <ECR_URI>:latest
   ```
3. **Deploy Infrastructure:**
   ```bash
   cd terraform
   terraform init
   terraform apply -auto-approve
   ```
4. **Ingest Knowledge Base Data:**
   ```bash
   # Run the script from root
   python python/ingest_kb.py
   ```
</details>

<details>
<summary><b>Running Security Scans</b></summary>

Hooks run automatically on `git commit`. **Moving forward, only modified/staged files are scanned per commit** to ensure speed and efficiency.

To run manually:
```bash
bash .husky/pre-commit
```
</details>

---

## 📖 Wiki & Live Verification Guide

<details>
<summary><b>1. Proof of Work (Task 1 Requirements)</b></summary>

- **AWS Agentcore:** Fully provisioned via `aws_bedrockagentcore_agent_runtime` in `terraform/main.tf`.
- **AWS Cognito:** Implemented `aws_cognito_user_pool` for secure inbound authorization.
- **FastAPI Hosting:** `python/main.py` serves the Agentcore `/invocations` and `/ping` contract.
- **LangGraph Orchestration:** `python/agent.py` implements a ReAct-type agent using `create_react_agent`.
- **Event Streaming:** Implemented using `.astream()` with `StreamingResponse(media_type="text/event-stream")`.
- **yfinance Integration:** Two native tools implemented in `python/tools.py` (`retrieve_realtime_stock_price`, `retrieve_historical_stock_price`).
- **RAG Knowledge Base:** Deployed `aws_bedrockagent_knowledge_base` with ingested 2024/2025 Amazon financial filings.
</details>

<details>
<summary><b>2. Live Verification Steps</b></summary>

Recruiters can verify the live deployment using the following steps:

1. **Open `invocation_demo.ipynb`**: This notebook contains the executable proof.
2. **Step 1: Identity Verification**: Run the first cell to authenticate against the Cognito User Pool. This proves the secure inbound authorization requirement.
3. **Step 2: Live Agent Invocation**: Run the second and third cells. This will call the **live AWS Agentcore URL**.
   - Observe the **Real-time Streaming**: Responses are yield token-by-token using Server-Sent Events (SSE).
   - Check the **Knowledge Base**: The agent will retrieve data from the 2024 Annual Report (e.g., North America office space) and 2025 releases.
4. **Step 3: Observability Audit**: Run the final cell. This fetches the trace data directly from the **Langfuse API**, proving that every reasoning step, tool call, and LLM interaction is being monitored and recorded.
</details>

<details>
<summary><b>3. Troubleshooting Verification</b></summary>

- **Expired Token**: If you receive a `401 Unauthorized`, re-run the Cognito authentication cell to refresh your Bearer token.
- **Empty Trace**: If Langfuse returns an empty array, ensure the `sessionId` in the API call matches the one used in the invocation headers.
</details>

---

**Policy:** This repository adheres to a 100% strict formatting and security policy (No skips permitted).

# AWS Financial AI Agent - Secure IaC & Containerized Deployment

A production-ready financial AI agent built with **FastAPI**, **LangGraph**, and **AWS Bedrock AgentCore**, featuring a rigorous automated security and linting pipeline.

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
- **Security Hardening:** Implemented non-root user (`appuser`) and pinned `pip` version.
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
   # BuildKit/buildx (avoids legacy builder deprecation warning)
   ./scripts/buildx_push.sh <ECR_URI> latest
   ```
3. **Deploy Infrastructure:**
   ```bash
   cd terraform
   terraform init
   terraform apply -auto-approve

   # Retrieve the IDs needed for the Notebook and Ingestion script
   terraform output
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

Users can verify the live deployment using the following steps:

1. **Open `invocation_demo.ipynb`**: This notebook contains the executable proof.
2. **AWS Authentication Phase**: Run the setup/alias cell. It loads runtime logic from GitHub and bootstraps passwordless AWS access (SigV4) from the runtime identity.
3. **Live Agent Invocation**: Run the query cell to call the **live AWS AgentCore runtime URL**.
   - Observe **real-time streaming** responses via SSE.
   - UI output is rendered as dark, left-justified floating chat boxes (Q/A) with markdown-aware formatting.
4. **Observability Audit**: Run the observability cell. It retrieves Langfuse credentials from AWS SSM and verifies trace API access.
</details>

<details>
<summary><b>3. Troubleshooting Verification</b></summary>

- **AWS CLI missing in runtime**: Re-run the setup cell. It installs `awscli` and falls back to `python -m awscli` when needed.
- **Expired Token**: Re-run the authentication/setup phase to refresh temporary AWS credentials.
- **No token counts in response**: Some AgentCore/model paths do not expose usage metadata. Notebook prints `Tokens: usage coming soon` for this case.
- **Empty Trace**: Ensure the `sessionId` in the Langfuse query matches the invocation session ID printed by the notebook.
</details>

---

**Policy:** This repository adheres to a 100% strict formatting and security policy (No skips permitted).

# Project TODOs & Future Enhancements

## 🔴 High Priority (Blockers)
- [ ] **Resolve Bedrock AgentCore 424 Error**: Investigate the persistent container startup failure in `us-east-1`. Potential steps:
    - Test deployment in a different region (e.g., `us-west-2`).
    - Verify container startup time and potentially optimize the FastAPI initialization.
    - Contact AWS Support regarding the "UnknownOperationException" in the preview runtime.

## 🟡 Medium Priority (Feature Gap)
- [ ] **Full OpenSearch Serverless Integration**: Move from the current S3-only retrieval to a complete Vector Database setup for the Knowledge Base.
- [ ] **Advanced Tooling**:
    - [ ] Implement `retrieve_news_sentiment` to analyze market sentiment alongside price data.
    - [ ] Add support for scraping analyst PDF reports directly from the web.
- [ ] **CI/CD Integration**: Setup GitHub Actions to automate Terraform plans and Docker builds on every PR.

## 🟢 Low Priority (Polish & UX)
- [ ] **Notebook UI Enhancement**: Add interactive widgets (e.g., `ipywidgets`) to allow recruiters to type custom ticker symbols.
- [ ] **Cost Optimization**: Refine `infracost` hooks to provide more granular usage-based cost estimates for Bedrock model invocations.
- [ ] **Security Auditing**: Perform a full manual IAM audit to transition from wildcard `*` resources to exact resource-level ARNs for all policies.

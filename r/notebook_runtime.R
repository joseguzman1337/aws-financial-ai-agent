suppressPackageStartupMessages({
  Sys.setenv(KMP_DUPLICATE_LIB_OK = "TRUE")
  library(reticulate)
})

default_cfg <- list(
  region = "us-east-1",
  agent_arn = "arn:aws:bedrock-agentcore:us-east-1:162187491349:runtime/Financial_Analyst_Agent-hvRgckAqaW",
  identity_pool_id = "us-east-1:c7680c24-fe96-4358-b305-6f43de1ca6c8",
  unauth_role_arn = "arn:aws:iam::162187491349:role/cognito_unauthenticated_role",
  credential_refresh_seconds = 45 * 60,
  model_id = "us.anthropic.claude-opus-4-6-v1"
)

default_params <- list(
  langfuse_pk = "/financial-ai/langfuse/public-key",
  langfuse_sk = "/financial-ai/langfuse/secret-key",
  langfuse_base_url = "/financial-ai/langfuse/base-url"
)

runtime_init <- function(cfg = default_cfg, params = default_params) {
  py_file <- Sys.getenv("NOTEBOOK_RUNTIME_PY_FILE", "/tmp/notebook_runtime_core.py")
  if (!file.exists(py_file)) {
    stop(sprintf("Python runtime core not found at %s", py_file))
  }
  source_python(py_file)
  core <- NotebookRuntimeCore(cfg = cfg, params = params)
  list(core = core)
}

refresh_clients <- function(rt) {
  rt$core$refresh_clients()
  rt
}

bootstrap_guest <- function(rt) {
  rt$core$bootstrap_guest()
  rt
}

ensure_fresh <- function(rt, force = FALSE) {
  rt$core$ensure_fresh(force = force)
  rt
}

ssm_get <- function(rt, name) {
  rt$core$ssm_get(name)
}

agent_url <- function(rt) {
  rt$core$agentcore_url
}

print_runtime_info_once <- function(rt) {
  rt$core$print_runtime_info_once()
  rt
}

query_agent <- function(rt, prompt) {
  rt$core$query_agent(prompt)
  rt
}

verify_observability <- function(rt) {
  rt$core$verify_observability()
  rt
}

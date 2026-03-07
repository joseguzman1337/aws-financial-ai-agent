suppressPackageStartupMessages({
  Sys.setenv(KMP_DUPLICATE_LIB_OK = "TRUE")
  library(jsonlite)
  library(httr)
  library(reticulate)
})

default_cfg <- list(
  region = "us-east-1",
  agent_arn = "arn:aws:bedrock-agentcore:us-east-1:162187491349:runtime/Financial_Analyst_Agent-hvRgckAqaW",
  identity_pool_id = "us-east-1:c7680c24-fe96-4358-b305-6f43de1ca6c8",
  unauth_role_arn = "arn:aws:iam::162187491349:role/cognito_unauthenticated_role",
  credential_refresh_seconds = 45 * 60
)

default_params <- list(
  langfuse_pk = "/financial-ai/langfuse/public-key",
  langfuse_sk = "/financial-ai/langfuse/secret-key",
  langfuse_base_url = "/financial-ai/langfuse/base-url"
)

runtime_init <- function(cfg = default_cfg, params = default_params) {
  boto3 <<- import("boto3")
  requests <<- import("requests")
  botocore <<- import("botocore")
  botocore_config <<- import("botocore.config")
  botocore_credentials <<- import("botocore.credentials")
  botocore_auth <<- import("botocore.auth")
  botocore_awsrequest <<- import("botocore.awsrequest")
  botocore_session <<- import("botocore.session")
  id <- as.character(reticulate::import("uuid")$uuid4())
  list(cfg = cfg, params = params, session_id = id, last_refresh = 0L)
}

refresh_clients <- function(rt) {
  if (!is.null(rt$credentials)) {
    rt$sts <- boto3$client(
      "sts",
      region_name = rt$cfg$region,
      aws_access_key_id = rt$credentials$AccessKeyId,
      aws_secret_access_key = rt$credentials$SecretAccessKey,
      aws_session_token = rt$credentials$SessionToken
    )
    rt$ssm <- boto3$client(
      "ssm",
      region_name = rt$cfg$region,
      aws_access_key_id = rt$credentials$AccessKeyId,
      aws_secret_access_key = rt$credentials$SecretAccessKey,
      aws_session_token = rt$credentials$SessionToken
    )
  } else {
    rt$sts <- boto3$client("sts", region_name = rt$cfg$region)
    rt$ssm <- boto3$client("ssm", region_name = rt$cfg$region)
  }
  rt
}

bootstrap_guest <- function(rt) {
  idc <- boto3$client(
    "cognito-identity",
    region_name = rt$cfg$region,
    config = botocore_config$Config(signature_version = botocore$UNSIGNED)
  )
  identity_id <- idc$get_id(IdentityPoolId = rt$cfg$identity_pool_id)[["IdentityId"]]
  token <- idc$get_open_id_token(IdentityId = identity_id)[["Token"]]
  creds <- boto3$client("sts", region_name = rt$cfg$region)$assume_role_with_web_identity(
    RoleArn = rt$cfg$unauth_role_arn,
    RoleSessionName = "NotebookGuestSession",
    WebIdentityToken = token
  )[["Credentials"]]
  Sys.setenv(
    AWS_ACCESS_KEY_ID = creds[["AccessKeyId"]],
    AWS_SECRET_ACCESS_KEY = creds[["SecretAccessKey"]],
    AWS_SESSION_TOKEN = creds[["SessionToken"]]
  )
  rt$credentials <- list(
    AccessKeyId = creds[["AccessKeyId"]],
    SecretAccessKey = creds[["SecretAccessKey"]],
    SessionToken = creds[["SessionToken"]]
  )
  rt <- refresh_clients(rt)
  rt$last_refresh <- as.integer(Sys.time())
  rt
}

ensure_fresh <- function(rt, force = FALSE) {
  age <- as.integer(Sys.time()) - as.integer(rt$last_refresh %||% 0L)
  if (force || is.null(rt$last_refresh) || rt$last_refresh == 0L || age >= rt$cfg$credential_refresh_seconds) {
    return(bootstrap_guest(rt))
  }
  tryCatch({
    rt$sts$get_caller_identity()
    rt
  }, error = function(e) bootstrap_guest(rt))
}

`%||%` <- function(x, y) if (is.null(x)) y else x

ssm_get <- function(rt, name) {
  tryCatch({
    rt$ssm$get_parameter(Name = name, WithDecryption = TRUE)[["Parameter"]][["Value"]]
  }, error = function(e) {
    if (grepl("ExpiredToken", conditionMessage(e), fixed = TRUE)) {
      rt2 <- bootstrap_guest(rt)
      rt2$ssm$get_parameter(Name = name, WithDecryption = TRUE)[["Parameter"]][["Value"]]
    } else {
      stop(e)
    }
  })
}

agent_url <- function(rt) {
  encoded <- URLencode(rt$cfg$agent_arn, reserved = TRUE)
  paste0("https://bedrock-agentcore.", rt$cfg$region, ".amazonaws.com/runtimes/", encoded, "/invocations")
}

query_agent <- function(rt, prompt) {
  rt <- ensure_fresh(rt)
  payload <- toJSON(list(prompt = prompt), auto_unbox = TRUE)
  url <- agent_url(rt)
  req <- botocore_awsrequest$AWSRequest(
    method = "POST",
    url = url,
    data = payload,
    headers = reticulate::dict(
      "Content-Type" = "application/json",
      "Accept" = "text/event-stream",
      "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id" = rt$session_id
    )
  )
  creds <- botocore_credentials$Credentials(
    access_key = rt$credentials$AccessKeyId,
    secret_key = rt$credentials$SecretAccessKey,
    token = rt$credentials$SessionToken
  )
  botocore_auth$SigV4Auth(creds, "bedrock-agentcore", rt$cfg$region)$add_auth(req)
  hdr_items <- reticulate::iterate(req$prepare()$headers$items(), simplify = FALSE)
  h <- setNames(
    vapply(hdr_items, function(kv) as.character(kv[[2]]), character(1)),
    vapply(hdr_items, function(kv) as.character(kv[[1]]), character(1))
  )
  cat("\n--- Query:", prompt, "---\n")
  r <- POST(url, add_headers(.headers = h), body = payload, encode = "raw", timeout(120))
  cat(substr(content(r, "text", encoding = "UTF-8"), 1, 2000), "\n")
  rt
}

verify_observability <- function(rt) {
  rt <- ensure_fresh(rt)
  pk <- ssm_get(rt, rt$params$langfuse_pk)
  sk <- ssm_get(rt, rt$params$langfuse_sk)
  base <- sub("/+$", "", ssm_get(rt, rt$params$langfuse_base_url))
  who <- rt$sts$get_caller_identity()[["Arn"]]
  cat("Observability identity:", who, "\n")
  cat("Success: retrieved Langfuse keys (PK:", substr(pk, 1, 7), "...)\n")
  auth <- GET(paste0(base, "/api/public/projects"), authenticate(pk, sk))
  cat("Langfuse auth status:", status_code(auth), "\n")
  rt
}

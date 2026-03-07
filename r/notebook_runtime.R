suppressPackageStartupMessages({
  Sys.setenv(KMP_DUPLICATE_LIB_OK = "TRUE")
  library(jsonlite)
  library(httr)
  library(reticulate)
})

event_text <- function(x) {
  if (is.null(x)) return("")
  if (is.character(x)) return(paste(x, collapse = ""))
  if (is.list(x)) {
    if (!is.null(x$text)) return(as.character(x$text))
    if (!is.null(x$content)) return(event_text(x$content))
    out <- vapply(x, event_text, character(1))
    return(paste(out, collapse = ""))
  }
  as.character(x)
}

pretty_print <- function(text, width = 79) {
  clean <- gsub("\\s+", " ", trimws(text))
  if (!nzchar(clean)) return(invisible(NULL))
  lines <- strwrap(clean, width = width)
  cat(paste(lines, collapse = "\n"), "\n", sep = "")
}

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
  boto3 <<- import("boto3")
  requests <<- import("requests")
  botocore <<- import("botocore")
  botocore_config <<- import("botocore.config")
  botocore_credentials <<- import("botocore.credentials")
  botocore_auth <<- import("botocore.auth")
  botocore_awsrequest <<- import("botocore.awsrequest")
  botocore_session <<- import("botocore.session")
  id <- as.character(reticulate::import("uuid")$uuid4())
  list(
    cfg = cfg,
    params = params,
    session_id = id,
    last_refresh = 0L,
    model_logged = FALSE,
    runtime_logged = FALSE
  )
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

runtime_id_from_arn <- function(agent_arn) {
  parts <- unlist(strsplit(agent_arn, "/", fixed = TRUE))
  parts[length(parts)]
}

print_runtime_info_once <- function(rt) {
  if (isTRUE(rt$runtime_logged)) return(rt)
  rid <- runtime_id_from_arn(rt$cfg$agent_arn)
  # Pull runtime/version/container directly via AWS CLI once.
  out <- tryCatch(
    system2(
      "aws",
      c(
        "bedrock-agentcore-control", "get-agent-runtime",
        "--region", rt$cfg$region,
        "--agent-runtime-id", rid,
        "--output", "json"
      ),
      stdout = TRUE, stderr = TRUE
    ),
    error = function(e) NULL
  )
  if (!is.null(out) && length(out) > 0) {
    js <- tryCatch(fromJSON(paste(out, collapse = "\n")), error = function(e) NULL)
    if (!is.null(js)) {
      version <- if (!is.null(js$agentRuntimeVersion)) as.character(js$agentRuntimeVersion) else "unknown"
      container <- tryCatch(
        as.character(js$agentRuntimeArtifact$containerConfiguration$containerUri),
        error = function(e) "unknown"
      )
      cat(
        sprintf(
          "Runtime: id=%s version=%s container=%s model=%s\n",
          rid, version, container, rt$cfg$model_id
        )
      )
      rt$runtime_logged <- TRUE
      rt$model_logged <- TRUE
      return(rt)
    }
  }
  cat(sprintf("Runtime: id=%s model=%s (runtime metadata not available)\n", rid, rt$cfg$model_id))
  rt$runtime_logged <- TRUE
  rt$model_logged <- TRUE
  rt
}

query_agent <- function(rt, prompt) {
  rt <- ensure_fresh(rt)
  rt <- print_runtime_info_once(rt)
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
  cat("\nQ: ")
  pretty_print(prompt, width = 79)
  r <- POST(url, add_headers(.headers = h), body = payload, encode = "raw", timeout(120))
  model_info <- NULL
  token_usage <- list(input = NULL, output = NULL, total = NULL)
  hdr_names <- tolower(names(headers(r)))
  model_hdr_idx <- grep("model|inference|profile", hdr_names)
  if (length(model_hdr_idx) > 0) {
    k <- names(headers(r))[model_hdr_idx[1]]
    v <- headers(r)[[k]]
    if (!is.null(v) && nzchar(as.character(v))) model_info <- paste0(k, ": ", as.character(v))
  }
  raw_txt <- content(r, "text", encoding = "UTF-8")
  lines <- unlist(strsplit(raw_txt, "\n", fixed = TRUE))
  parts <- character(0)
  for (ln in lines) {
    ln <- trimws(ln)
    if (!startsWith(ln, "data:")) next
    payload_json <- sub("^data:\\s*", "", ln)
    evt <- tryCatch(fromJSON(payload_json), error = function(e) NULL)
    if (is.null(evt)) next
    if (!is.null(evt$error)) {
      parts <- c(parts, paste0("Error: ", as.character(evt$error)))
      next
    }
    if (!is.null(evt$usage) && is.list(evt$usage)) {
      u <- evt$usage
      if (!is.null(u$inputTokens)) token_usage$input <- as.integer(u$inputTokens)
      if (!is.null(u$outputTokens)) token_usage$output <- as.integer(u$outputTokens)
      if (!is.null(u$totalTokens)) token_usage$total <- as.integer(u$totalTokens)
      if (!is.null(u$promptTokens)) token_usage$input <- as.integer(u$promptTokens)
      if (!is.null(u$completionTokens)) token_usage$output <- as.integer(u$completionTokens)
    }
    if (!is.null(evt$tokenUsage) && is.list(evt$tokenUsage)) {
      u <- evt$tokenUsage
      if (!is.null(u$inputTokens)) token_usage$input <- as.integer(u$inputTokens)
      if (!is.null(u$outputTokens)) token_usage$output <- as.integer(u$outputTokens)
      if (!is.null(u$totalTokens)) token_usage$total <- as.integer(u$totalTokens)
    }
    if (!is.null(evt$inputTokens)) token_usage$input <- as.integer(evt$inputTokens)
    if (!is.null(evt$outputTokens)) token_usage$output <- as.integer(evt$outputTokens)
    if (!is.null(evt$totalTokens)) token_usage$total <- as.integer(evt$totalTokens)
    if (is.null(model_info)) {
      for (mk in c("model", "modelId", "model_id", "inferenceProfileId", "inference_profile_id", "foundationModel")) {
        if (!is.null(evt[[mk]]) && nzchar(as.character(evt[[mk]]))) {
          model_info <- paste0(mk, ": ", as.character(evt[[mk]]))
          break
        }
      }
    }
    if (!is.null(evt$event)) parts <- c(parts, event_text(evt$event))
  }
  if (!isTRUE(rt$model_logged)) {
    if (is.null(model_info) || !nzchar(trimws(model_info))) {
      cat("Model: not exposed by AgentCore response metadata\n")
    } else {
      cat("Model:", model_info, "\n")
    }
    rt$model_logged <- TRUE
  }
  answer <- trimws(paste(parts, collapse = " "))
  cat("A: ")
  pretty_print(answer, width = 79)
  if (is.null(token_usage$total) && !is.null(token_usage$input) && !is.null(token_usage$output)) {
    token_usage$total <- as.integer(token_usage$input + token_usage$output)
  }
  if (!is.null(token_usage$input) || !is.null(token_usage$output) || !is.null(token_usage$total)) {
    cat(sprintf(
      "Tokens: input=%s output=%s total=%s\n",
      ifelse(is.null(token_usage$input), "n/a", as.character(token_usage$input)),
      ifelse(is.null(token_usage$output), "n/a", as.character(token_usage$output)),
      ifelse(is.null(token_usage$total), "n/a", as.character(token_usage$total))
    ))
  } else {
    cat("Tokens: not exposed by AgentCore response metadata\n")
  }
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

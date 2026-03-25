#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  need <- c("httr2", "jsonlite", "yaml", "dplyr", "purrr", "tibble")
  missing <- need[!vapply(need, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing)) install.packages(missing, repos = "https://cloud.r-project.org", quiet = TRUE)
  invisible(lapply(need, library, character.only = TRUE))
})

run_cmd <- function(cmd) {
  out <- tryCatch(
    suppressWarnings(system(cmd, intern = TRUE, ignore.stderr = TRUE)),
    error = function(e) character(0)
  )
  if (!length(out)) return("")
  trimws(paste(out, collapse = "\n"))
}

get_ssm <- function(name) {
  cmd <- sprintf("aws ssm get-parameter --name %s --with-decryption --query Parameter.Value --output text", shQuote(name))
  val <- run_cmd(cmd)
  if (!nzchar(val)) stop(sprintf("Failed to read SSM parameter: %s", name))
  val
}

whoami_aws <- function() {
  run_cmd("aws sts get-caller-identity --output json")
}

base_dir <- getwd()
out_dir <- file.path(base_dir, "artifacts", "langfuse")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

ssm_pk <- Sys.getenv("LANGFUSE_PK_PARAM", "/financial-ai/langfuse/public-key")
ssm_sk <- Sys.getenv("LANGFUSE_SK_PARAM", "/financial-ai/langfuse/secret-key")
ssm_base <- Sys.getenv("LANGFUSE_BASE_PARAM", "/financial-ai/langfuse/base-url")

pk <- tryCatch(get_ssm(ssm_pk), error = function(e) {
  ident <- whoami_aws()
  stop(
    paste(
      "Failed to read Langfuse public key from SSM.",
      "Check AWS credentials/session and ssm:GetParameter permission.",
      if (nzchar(ident)) paste("Current identity:", ident) else "",
      sep = "\n"
    )
  )
})
sk <- get_ssm(ssm_sk)
base_url <- sub("/$", "", get_ssm(ssm_base))

if (grepl("placeholder|00000000", tolower(sk))) {
  stop("Langfuse secret appears to be placeholder; aborting report generation")
}

openapi_path <- file.path(base_dir, "docs", "langfuse", "openapi.yml")
if (!file.exists(openapi_path)) {
  openapi_url <- Sys.getenv("LANGFUSE_OPENAPI_URL", "https://cloud.langfuse.com/generated/api/openapi.yml")
  req <- request(openapi_url) |> req_timeout(30)
  resp <- req_perform(req)
  writeLines(resp_body_string(resp), openapi_path)
}

spec <- yaml::read_yaml(openapi_path)
paths <- names(spec$paths)

# Probe only GET endpoints without path params.
probe_paths <- paths[grepl("^/api/public", paths) & !grepl("\\{", paths)]
probe_get <- probe_paths[vapply(probe_paths, function(p) {
  is.list(spec$paths[[p]]) && !is.null(spec$paths[[p]]$get)
}, logical(1))]

api_get <- function(path, query = list()) {
  req <- request(paste0(base_url, path)) |>
    req_auth_basic(pk, sk) |>
    req_url_query(!!!query) |>
    req_timeout(30)
  resp <- req_perform(req)
  list(
    status = resp_status(resp),
    headers = resp_headers(resp),
    body_text = resp_body_string(resp)
  )
}

safe_json <- function(txt) {
  tryCatch(jsonlite::fromJSON(txt, simplifyVector = FALSE), error = function(e) NULL)
}

`%||%` <- function(x, y) if (is.null(x)) y else x

probe_rows <- purrr::map(probe_get, function(p) {
  q <- list(limit = 5)
  if (p == "/api/public/traces") q$sessionId <- Sys.getenv("LANGFUSE_SESSION_ID", "")

  res <- tryCatch(api_get(p, q), error = function(e) list(status = -1L, body_text = as.character(e), headers = list()))
  js <- safe_json(res$body_text)
  top_keys <- if (is.list(js)) paste(sort(names(js)), collapse = ",") else ""
  data_count <- if (is.list(js) && !is.null(js$data) && is.list(js$data)) length(js$data) else NA_integer_
  tibble::tibble(
    endpoint = p,
    status = as.integer(res$status),
    content_type = as.character(res$headers[["content-type"]] %||% ""),
    top_level_keys = top_keys,
    data_count = data_count
  )
}) |> dplyr::bind_rows() |> dplyr::arrange(status, endpoint)

# Canonical pulls for common observability entities.
fetch_entity <- function(path, q = list(limit = 200)) {
  res <- tryCatch(api_get(path, q), error = function(e) NULL)
  if (is.null(res) || res$status != 200) return(list(path = path, status = ifelse(is.null(res), -1, res$status), data = list()))
  js <- safe_json(res$body_text)
  data <- if (is.list(js) && !is.null(js$data)) js$data else list()
  list(path = path, status = 200L, data = data, raw = js)
}

traces <- fetch_entity("/api/public/traces", list(limit = 100, sessionId = Sys.getenv("LANGFUSE_SESSION_ID", "")))
obs_v1 <- fetch_entity("/api/public/observations", list(limit = 200))
sessions <- fetch_entity("/api/public/sessions", list(limit = 100))
datasets_v2 <- fetch_entity("/api/public/v2/datasets", list(limit = 100))

flatten_rows <- function(x) {
  if (!length(x)) return(tibble::tibble())
  purrr::map_dfr(x, function(item) {
    if (!is.list(item)) return(tibble::tibble(value = as.character(item)))
    # Keep scalar columns only for stable rectangular export.
    scalars <- item[vapply(item, function(v) is.atomic(v) && length(v) <= 1, logical(1))]
    tibble::as_tibble(scalars)
  })
}

traces_df <- flatten_rows(traces$data)
obs_df <- flatten_rows(obs_v1$data)
sessions_df <- flatten_rows(sessions$data)
datasets_df <- flatten_rows(datasets_v2$data)

# Export full artifact bundle.
report <- list(
  generated_at = as.character(Sys.time()),
  base_url = base_url,
  openapi_path = openapi_path,
  probe = probe_rows,
  entities = list(
    traces = traces,
    observations_v1 = obs_v1,
    sessions = sessions,
    datasets_v2 = datasets_v2
  )
)

saveRDS(report, file.path(out_dir, "langfuse_full_report.rds"))
writeLines(jsonlite::toJSON(report, auto_unbox = TRUE, pretty = TRUE, null = "null"), file.path(out_dir, "langfuse_full_report.json"))
write.csv(probe_rows, file.path(out_dir, "langfuse_endpoint_probe.csv"), row.names = FALSE)
if (nrow(traces_df)) write.csv(traces_df, file.path(out_dir, "traces_flat.csv"), row.names = FALSE)
if (nrow(obs_df)) write.csv(obs_df, file.path(out_dir, "observations_flat.csv"), row.names = FALSE)
if (nrow(sessions_df)) write.csv(sessions_df, file.path(out_dir, "sessions_flat.csv"), row.names = FALSE)
if (nrow(datasets_df)) write.csv(datasets_df, file.path(out_dir, "datasets_flat.csv"), row.names = FALSE)

cat(sprintf(
  "Langfuse report complete: probes=%d traces=%d observations=%d sessions=%d datasets=%d -> %s\n",
  nrow(probe_rows), nrow(traces_df), nrow(obs_df), nrow(sessions_df), nrow(datasets_df), out_dir
))

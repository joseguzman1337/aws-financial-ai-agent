#!/bin/sh
set -eu

# Run R checks only for staged R files.
STAGED_R_FILES="$(git diff --cached --name-only --diff-filter=ACMR | grep -E '\.R$' || true)"

if [ -z "${STAGED_R_FILES}" ]; then
  echo "R quality: no staged .R files; skipping."
  exit 0
fi

if ! command -v Rscript >/dev/null 2>&1; then
  echo "R quality: Rscript not found. Install R to enable R lint/format checks."
  exit 1
fi

echo "R quality: formatting + linting staged R files..."

# Use a single R process for dependency checks, syntax parse, style fix, and lint.
R_STAGED_FILES="${STAGED_R_FILES}" Rscript - <<'RS'
files <- strsplit(Sys.getenv("R_STAGED_FILES"), "\n", fixed = TRUE)[[1]]
files <- files[nzchar(files)]
if (!length(files)) quit(status = 0)

required <- c("styler", "lintr")
missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) {
  stop(
    sprintf(
      "Missing R packages: %s. Install with install.packages(c(%s))",
      paste(missing, collapse = ", "),
      paste(sprintf('"%s"', missing), collapse = ", ")
    )
  )
}

# Syntax/parse check first (fast fail).
for (f in files) parse(file = f)

# Auto-fix style in place.
for (f in files) styler::style_file(path = f, strict = FALSE)

# Lint and fail on findings.
lints <- unlist(lapply(files, lintr::lint), recursive = FALSE)
if (length(lints) > 0) {
  print(lints)
  stop(sprintf("R lint failed with %d issue(s).", length(lints)))
}

cat(sprintf("R quality passed for %d file(s).\n", length(files)))
RS

# Re-stage any style changes.
echo "${STAGED_R_FILES}" | while IFS= read -r f; do
  [ -n "$f" ] && git add "$f"
done


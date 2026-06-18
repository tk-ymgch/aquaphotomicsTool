local_lib <- Sys.getenv("AQUA_R_LIBS", file.path(getwd(), "r_libs"))
dir.create(local_lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(normalizePath(local_lib, mustWork = FALSE), .libPaths()))
options(repos = c(CRAN = "https://cloud.r-project.org"))

message("R library path: ", normalizePath(local_lib, mustWork = FALSE))

install_missing <- function(pkg) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    message("Installing ", pkg, " ...")
    utils::install.packages(pkg, lib = local_lib, dependencies = TRUE, Ncpus = max(1, min(2, parallel::detectCores(logical = TRUE))))
  } else {
    message(pkg, " is already available")
  }
}

status <- TRUE
tryCatch({
  install_missing("aquap2")
}, error = function(e) {
  status <<- FALSE
  message("CRAN install failed: ", conditionMessage(e))
})

if (!requireNamespace("aquap2", quietly = TRUE)) {
  message("Trying GitHub install via remotes ...")
  tryCatch({
    install_missing("remotes")
    remotes::install_github("bpollner/aquap2", ref = "latestPublic", lib = local_lib, dependencies = TRUE, upgrade = "never")
  }, error = function(e) {
    status <<- FALSE
    message("GitHub install failed: ", conditionMessage(e))
  })
}

if (requireNamespace("aquap2", quietly = TRUE)) {
  message("aquap2 ready: ", as.character(utils::packageVersion("aquap2")))
  quit(status = 0)
}

message("aquap2 is not available after setup.")
quit(status = 1)

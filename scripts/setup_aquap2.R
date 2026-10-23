#!/usr/bin/env Rscript
# Official downloads; write only a dedicated qa runtime, never system libraries.
args <- commandArgs(trailingOnly = TRUE)
file_arg <- grep("^--file=", commandArgs(FALSE), value = TRUE)
script <- normalizePath(sub("^--file=", "", file_arg[1]), winslash = "/", mustWork = TRUE)
project <- dirname(dirname(script))
runtime <- if (length(args)) args[1] else file.path(project, "qa/aquap2-runtime-v1.4")
if (length(args) > 1L) stop("Usage: Rscript scripts/setup_aquap2.R [runtime-directory]")
runtime <- normalizePath(runtime, winslash = "/", mustWork = FALSE)
qa <- paste0(tolower(normalizePath(file.path(project, "qa"), winslash = "/", mustWork = FALSE)), "/")
if (!startsWith(paste0(tolower(runtime), "/"), qa) || identical(tolower(runtime), sub("/$", "", qa))) {
  stop("Runtime must be a dedicated directory below this project's qa folder.")
}
for (folder in c("", "library", "downloads", "source", "home", "settings", "temp", "jobs")) {
  dir.create(file.path(runtime, folder), recursive = TRUE, showWarnings = FALSE)
}
lib <- normalizePath(file.path(runtime, "library"), winslash = "/")
.libPaths(c(lib, .Library))
Sys.setenv(R_USER = file.path(runtime, "home"), AQUAP2SH = file.path(runtime, "settings"),
           R_LIBS_USER = lib, TMPDIR = file.path(runtime, "temp"))
writeLines(paste0("AQUAP2SH = ", file.path(runtime, "settings")),
           file.path(runtime, "home/.Renviron"), useBytes = TRUE)
options(timeout = 300, repos = c(CRAN = "https://cloud.r-project.org"), download.file.method = "libcurl")
commit <- "d31c1231bf71f0e73f1a630a32934602782be488"
expected_archive_sha256 <- "22e6582a7205a723f0f70e3e3c91db272f3eefcb4eabb29023a9229091df0130"
archive <- file.path(runtime, "aquap2-pinned.zip")
if (!file.exists(archive)) {
  download.file(paste0("https://codeload.github.com/bpollner/aquap2/zip/", commit), archive, mode = "wb")
}
# digest/jsonlite themselves are CRAN packages; all destination writes stay in lib.
for (package in c("digest", "jsonlite")) {
  if (!requireNamespace(package, quietly = TRUE)) {
    install.packages(package, lib = lib, type = if (.Platform$OS.type == "windows") "binary" else "source",
                     destdir = file.path(runtime, "downloads"))
  }
}
sha256_file <- function(path) digest::digest(readBin(path, "raw", n = file.info(path)$size),
                                           serialize = FALSE, algo = "sha256")
if (sha256_file(archive) != expected_archive_sha256) {
  stop("Official fixed-commit archive SHA-256 differs; no package install performed.")
}
archive_listing <- unzip(archive, list = TRUE)$Name
prefix <- paste0("aquap2-", commit, "/")
if (any(!startsWith(archive_listing, prefix)) || any(grepl("(^|/)\\.\\.(/|$)|^[/\\\\]|^[A-Za-z]:", archive_listing))) {
  stop("Unexpected source archive paths.")
}
unpacked <- file.path(runtime, "unpacked")
dir.create(unpacked, showWarnings = FALSE)
unzip(archive, exdir = unpacked)
source <- file.path(unpacked, paste0("aquap2-", commit))
description <- read.dcf(file.path(source, "DESCRIPTION"))
if (description[1, "Version"] != "0.4.5") stop("Pinned package version differs.")
imports <- trimws(strsplit(gsub("[\r\n]", "", description[1, "Imports"]), ",")[[1]])
missing <- imports[!vapply(imports, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) {
  install.packages(missing, lib = lib, dependencies = c("Depends", "Imports", "LinkingTo"),
                   type = if (.Platform$OS.type == "windows") "binary" else "source",
                   destdir = file.path(runtime, "downloads"))
}
remaining <- imports[!vapply(imports, requireNamespace, logical(1), quietly = TRUE)]
if (length(remaining)) stop(paste("Missing dependencies:", paste(remaining, collapse = ", ")))
already_pinned <- FALSE
receipt_file <- file.path(runtime, "installation.json")
if (file.exists(receipt_file)) {
  previous <- tryCatch(jsonlite::fromJSON(receipt_file), error = function(e) NULL)
  if (!is.null(previous) && identical(previous$sourceCommit, commit) &&
      requireNamespace("aquap2", quietly = TRUE, lib.loc = lib) &&
      read.dcf(file.path(lib, "aquap2/DESCRIPTION"))[1,"Version"] == "0.4.5") {
    already_pinned <- TRUE
    for (i in seq_len(nrow(previous$installedFiles))) {
      target <- file.path(lib, "aquap2", previous$installedFiles$path[i])
      if (!file.exists(target) || sha256_file(target) != previous$installedFiles$sha256[i]) {
        already_pinned <- FALSE
      }
    }
  }
}
if (!already_pinned) {
  if ("aquap2" %in% loadedNamespaces()) unloadNamespace("aquap2")
  cmd <- file.path(R.home("bin"), if (.Platform$OS.type == "windows") "Rcmd.exe" else "R")
  status <- system2(cmd, c("INSTALL", shQuote(paste0("--library=", lib)), shQuote(source)),
                    stdout = file.path(runtime, "install-aquap2.log"),
                    stderr = file.path(runtime, "install-aquap2.log"))
  if (status != 0L) stop("aquap2 installation failed; inspect runtime/install-aquap2.log")
}
suppressPackageStartupMessages(library(aquap2, lib.loc = lib))
if (read.dcf(file.path(lib, "aquap2/DESCRIPTION"))[1,"Version"] != "0.4.5") stop("Installed version differs.")
installed_files <- c("DESCRIPTION", "NAMESPACE", "R/aquap2.rdb", "R/aquap2.rdx")
receipt <- list(schemaVersion = 1L, sourceCommit = commit, aquap2Version = "0.4.5",
  sourceArchiveUrl = paste0("https://codeload.github.com/bpollner/aquap2/zip/", commit),
  sourceArchiveSha256 = expected_archive_sha256, rVersion = R.version.string,
  installedAt = format(Sys.time(), tz = "UTC", usetz = TRUE),
  installedFiles = lapply(installed_files, function(path) list(path = path,
    sha256 = sha256_file(file.path(lib, "aquap2", path)))))
jsonlite::write_json(receipt, receipt_file, pretty = TRUE, auto_unbox = TRUE)
# list.dirs + read.dcf also works for Unicode Windows paths on R versions where
# installed.packages(lib.loc=...) may return an empty matrix unexpectedly.
descriptions <- list.files(lib, pattern = "^DESCRIPTION$", recursive = TRUE, full.names = TRUE)
descriptions <- descriptions[dirname(dirname(descriptions)) == lib]
versions <- do.call(rbind, lapply(descriptions, function(path) {
  d <- read.dcf(path); data.frame(Package = d[1,"Package"], Version = d[1,"Version"], stringsAsFactors = FALSE)
}))
write.csv(versions, file.path(runtime, "installed-versions.csv"), row.names = FALSE)
cat("Installed pinned aquap2 0.4.5 and dependencies in the isolated runtime.\n")
cat("Before starting aquap2_engine.R, set AQUAP2_LIBRARY to runtime/library and R_USER to runtime/home.\n")

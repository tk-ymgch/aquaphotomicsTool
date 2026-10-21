#!/usr/bin/env Rscript
# Independent oracle: installed aquap2 0.4.5 and public gdmm/dpt.pre/getcm.
# This script is verification infrastructure, not an aquap2py runtime dependency.
args <- commandArgs(trailingOnly = TRUE)
script_arg <- grep("^--file=", commandArgs(FALSE), value = TRUE)[1]
project <- dirname(dirname(normalizePath(sub("^--file=", "", script_arg), winslash = "/", mustWork = TRUE)))
root <- normalizePath(Sys.getenv("AQUAP2_RUNTIME_ROOT", file.path(project, "qa/aquap2-runtime-v1.4")), winslash = "/", mustWork = TRUE)
lib <- normalizePath(Sys.getenv("AQUAP2_LIBRARY", file.path(root, "library")), winslash = "/", mustWork = TRUE)
.libPaths(c(lib, .Library))
if (!requireNamespace("jsonlite", quietly = TRUE)) stop("Installed jsonlite is required.")
if (length(args) != 2L) stop("Usage: Rscript --vanilla aquap2py_oracle.R input.json output.json")
runtime <- NULL
read_raw <- function(path) readBin(path, "raw", n = file.info(path)$size)
as_num <- function(x, name) {
  if (!is.list(x) || !length(x) || any(!vapply(x, function(v) is.numeric(v) && length(v) == 1L && is.finite(v), logical(1)))) stop(paste(name, "must be finite numeric array."))
  unlist(x, use.names = FALSE)
}
integer_value <- function(x, low, high, name) {
  if (!is.numeric(x) || length(x) != 1L || !is.finite(x) || x != floor(x) || x < low || x > high) stop(paste("Invalid", name))
  as.integer(x)
}
run <- function(input) {
  expected_home <- normalizePath(file.path(root, "home"), winslash = "/", mustWork = TRUE)
  if (!identical(tolower(normalizePath(Sys.getenv("HOME"), winslash = "/", mustWork = TRUE)), tolower(expected_home))) stop("Set R_USER to the isolated runtime home before R starts.")
  receipt <- jsonlite::parse_json(rawToChar(read_raw(file.path(root, "installation.json"))))
  pin <- "d31c1231bf71f0e73f1a630a32934602782be488"
  if (!identical(receipt$sourceCommit, pin) || !identical(receipt$sourceArchiveSha256, "22e6582a7205a723f0f70e3e3c91db272f3eefcb4eabb29023a9229091df0130")) stop("Pinned installation receipt mismatch.")
  package <- find.package("aquap2", lib.loc = lib)
  if (!requireNamespace("digest", quietly = TRUE) || length(receipt$installedFiles) != 4L) stop("Package verification prerequisites missing.")
  for (entry in receipt$installedFiles) {
    if (!entry$path %in% c("DESCRIPTION", "NAMESPACE", "R/aquap2.rdb", "R/aquap2.rdx") ||
        !identical(digest::digest(read_raw(file.path(package, entry$path)), algo = "sha256", serialize = FALSE), entry$sha256)) stop("Installed package integrity mismatch.")
  }
  suppressPackageStartupMessages(library(aquap2, lib.loc = lib))
  package_version <- function(name) unname(read.dcf(file.path(find.package(name, lib.loc = lib), "DESCRIPTION"))[1, "Version"])
  if (package_version("aquap2") != "0.4.5") stop("The oracle requires installed aquap2 0.4.5.")
  runtime <<- list(engine = "aquap2", installedPackage = TRUE, aquap2Version = "0.4.5",
    rVersion = R.version.string, sourceCommit = pin, api = "aquap2::gdmm",
    packageApiExecuted = FALSE, gdmmAttempted = FALSE, sourceHarnessUsed = FALSE,
    preprocessing = "installed-aquap2-public-gdmm-dpt.pre", signalVersion = package_version("signal"),
    plsVersion = package_version("pls"))
  if (!is.list(input) || input$schemaVersion != 1) stop("Invalid schema.")
  w <- as_num(input$wavelengths, "wavelengths")
  ids <- enc2utf8(unlist(input$ids, use.names = FALSE)); groups <- enc2utf8(unlist(input$groups, use.names = FALSE))
  n <- length(ids); p <- length(w)
  if (n < 2L || p < 3L || n * p > 2000000L || p > 10000L || min(n, p) > 1000L ||
      length(groups) != n || anyDuplicated(ids) || any(diff(w) <= 0) || any(w <= 0)) stop("Invalid dimensions/labels/wavelengths.")
  if (!is.list(input$matrix) || length(input$matrix) != n || any(vapply(input$matrix, length, integer(1)) != p)) stop("Invalid input matrix shape.")
  x <- do.call(rbind, lapply(input$matrix, as_num, name = "matrix"))
  if (any(rowSums(abs(x)) == 0)) stop("All-zero input rows would be removed by ttap; excluded oracle input.")
  k <- integer_value(input$pca$components, 1, min(10, n - 1L, p), "components")
  if (!identical(input$pca$scale, FALSE)) stop("PCA scaling is not supported.")
  targets <- as_num(input$aquagram$wavelengths, "targets")
  if (length(targets) < 3L || anyDuplicated(targets) || any(!targets %in% w)) stop("Targets must be actual columns.")
  targets <- w[w %in% targets]
  reference <- input$aquagram$reference
  if (identical(reference, "global")) { mode <- "classic"; control <- NULL } else if (is.character(reference) && startsWith(reference, "group:") && substring(reference, 7) %in% groups) {
    mode <- "classic-diff"; control <- substring(reference, 7)
  } else stop("Unsupported reference.")
  steps <- input$steps
  if (!is.list(steps) || length(steps) > 32L) stop("Invalid steps.")
  dpt <- character()
  for (step in steps) {
    method <- step$method
    if (identical(method, "snv") && setequal(names(step), "method")) dpt <- c(dpt, "snv") else
    if (identical(method, "msc") && setequal(names(step), "method")) dpt <- c(dpt, "msc") else
    if (identical(method, "sgolay") && all(names(step) %in% c("method", "window", "polyorder", "derivative", "delta"))) {
      win <- integer_value(if (is.null(step$window)) 21 else step$window, 3, min(501, p), "SG window")
      pol <- integer_value(if (is.null(step$polyorder)) 2 else step$polyorder, 0, min(6, win - 1L), "SG polyorder")
      der <- integer_value(if (is.null(step$derivative)) 0 else step$derivative, 0, min(2, pol), "SG derivative")
      if (win %% 2L != 1L || !is.null(step$delta) && !identical(as.numeric(step$delta), 1)) stop("Invalid SG spacing/window.")
      dpt <- c(dpt, paste0("sgol@", pol, "-", win, "-", der))
    } else stop("Unsupported preprocessing method/options.")
  }
  aq_sg <- integer_value(input$aqSmoothN, 3, min(501, p), "Aquagram SG")
  if (aq_sg %% 2L != 1L) stop("Aquagram SG must be odd.")
  settings <- file.path(root, "settings"); Sys.setenv(AQUAP2SH = settings)
  writeLines(paste0("AQUAP2SH = ", settings), file.path(expected_home, ".Renviron"), useBytes = TRUE)
  aquap2::updateSettings(silent = TRUE)
  jobs <- file.path(root, "jobs"); dir.create(jobs, showWarnings = FALSE)
  job <- tempfile("aquap2py-oracle-", tmpdir = jobs); dir.create(job)
  previous <- getwd()
  on.exit({setwd(previous); target <- normalizePath(job, winslash = "/", mustWork = FALSE); parent <- paste0(normalizePath(jobs, winslash = "/", mustWork = TRUE), "/"); if (startsWith(tolower(target), tolower(parent)) && startsWith(basename(target), "aquap2py-oracle-")) unlink(target, recursive = TRUE, force = TRUE)}, add = TRUE)
  setwd(job); aquap2::genFolderStr()
  md <- aquap2::getmd(expName = "aquap2py-native-preprocessing-oracle")
  rows <- sprintf("ROW%07d", seq_len(n)); names <- unique(groups); tokens <- sprintf("G%06d", seq_along(names)); gi <- match(groups, names)
  header <- data.frame(C_all = factor(rep("all", n)), C_Group = factor(tokens[gi], levels = tokens),
    C_ECRM = factor(rep("RM", n)), Y_SampleNr = seq_len(n), Y_conSNr = rep(1, n), row.names = rows)
  rownames(x) <- rows; colnames(x) <- paste0("w", format(w, scientific = FALSE, trim = TRUE, digits = 17))
  fd <- aquap2::ttap(list(header = header, NIR = x), md = md, dol = FALSE, ncpwl = 1, stf = FALSE)
  ap <- do.call(aquap2::getap, list(do.pca = TRUE, do.aqg = TRUE, do.pls = FALSE, do.sim = FALSE,
    do.da = FALSE, do.rnf = FALSE, do.svm = FALSE, do.nnet = FALSE,
    spl.var = NULL, spl.wl = NULL, dpt.pre = if (!length(dpt)) NULL else dpt, dpt.post = NULL,
    spl.do.csAvg = FALSE, spl.do.noise = FALSE, spl.do.exOut = FALSE,
    aqg.vars = "C_Group", aqg.mod = mode, aqg.minus = if (is.null(control)) NULL else tokens[match(control, names)],
    aqg.smoothN = aq_sg, aqg.msc = FALSE, aqg.nrCorr = FALSE, aqg.bootCI = FALSE, aqg.spectra = FALSE, aqg.selWls = targets))
  runtime$gdmmAttempted <<- TRUE
  cube <- aquap2::gdmm(fd, ap = ap)
  runtime$packageApiExecuted <<- TRUE
  if (length(cube) != 1L) stop("Unexpected dataset splits.")
  used <- aquap2::getcd(cube, 1)
  if (!identical(rownames(used$NIR), rows) || !identical(dim(used$NIR), dim(x))) stop("Row alignment changed in installed package.")
  model <- aquap2::getcm(cube, 1, what = "pca")$model
  aq <- aquap2::getcm(cube, 1, what = "aquagr")[[1]]
  avg <- aq@avg
  if (!all(is.finite(used$NIR)) || !all(is.finite(model$scores)) || !all(is.finite(avg)) || !is.finite(model$totalvar) || model$totalvar <= 0) stop("Oracle post-API finite-result guard rejected degenerate output.")
  runtime$nativeDptSteps <- I(dpt); runtime$aqSmoothN <- aq_sg; runtime$aqMsc <- FALSE
  runtime$inputSamples <- n; runtime$inputVariables <- p; runtime$rowAlignmentPreserved <- TRUE
  list(schemaVersion = 1L, ok = TRUE, runtime = runtime, ids = I(ids), groups = I(groups), wavelengths = I(w),
    preprocessed = unname(as.matrix(used$NIR)),
    pca = list(scores = unname(model$scores[, seq_len(k), drop = FALSE]), loadings = unname(model$loadings[, seq_len(k), drop = FALSE]), explainedVariance = I(unname(model$var[seq_len(k)] / model$totalvar))),
    aquagram = list(wavelengths = I(targets), groups = lapply(seq_along(names), function(i) list(name = names[i], values = I(unname(avg[tokens[i], ])), n = sum(gi == i))), mode = mode, ddof = 1L))
}
sink(stderr(), type = "output")
result <- tryCatch(run(jsonlite::parse_json(rawToChar(read_raw(args[1])), simplifyVector = FALSE)), error = function(e) list(schemaVersion = 1L, ok = FALSE, error = list(type = class(e)[1], message = conditionMessage(e)), runtime = runtime))
sink(type = "output")
output <- enc2utf8(as.character(jsonlite::toJSON(result, auto_unbox = TRUE, digits = NA, matrix = "rowmajor", null = "null", na = "null")))
writeBin(charToRaw(paste0(output, "\n")), args[2])
quit(status = if (isTRUE(result$ok)) 0L else 1L)

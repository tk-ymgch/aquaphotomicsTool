#!/usr/bin/env Rscript
# Verification oracle only. Installed aquap2 0.4.5 public APIs; no source harness.
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) stop("Usage: Rscript --vanilla temperature_oracle.R input.json output.json")
script <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])
project <- dirname(dirname(normalizePath(script, winslash = "/", mustWork = TRUE)))
runtime_root <- Sys.getenv("AQUAP2_RUNTIME_ROOT", file.path(project, "qa/aquap2-runtime-v1.4"))
lib <- normalizePath(Sys.getenv("AQUAP2_LIBRARY", file.path(runtime_root, "library")), winslash = "/", mustWork = TRUE)
.libPaths(c(lib, .Library))
read_raw <- function(path) readBin(path, "raw", n = file.info(path)$size)
runtime <- NULL
numeric_array <- function(x) {
  if (!is.list(x) || !length(x) || any(!vapply(x, function(z) is.numeric(z) && length(z) == 1L && is.finite(z), logical(1)))) stop("Expected finite numeric array.")
  unlist(x, use.names = FALSE)
}
numeric_matrix <- function(x) {
  if (!is.list(x) || length(x) < 2L || length(unique(vapply(x, length, integer(1)))) != 1L) stop("Invalid matrix shape.")
  result <- do.call(rbind, lapply(x, numeric_array))
  if (ncol(result) < 3L || length(result) > 2000000L) stop("Invalid matrix size.")
  result
}
run <- function(input) {
  receipt <- jsonlite::parse_json(rawToChar(read_raw(file.path(runtime_root, "installation.json"))))
  pin <- "d31c1231bf71f0e73f1a630a32934602782be488"
  if (!identical(receipt$sourceCommit, pin) || !identical(receipt$sourceArchiveSha256, "22e6582a7205a723f0f70e3e3c91db272f3eefcb4eabb29023a9229091df0130")) stop("Pinned receipt mismatch.")
  package <- find.package("aquap2", lib.loc = lib)
  for (entry in receipt$installedFiles) {
    if (!entry$path %in% c("DESCRIPTION", "NAMESPACE", "R/aquap2.rdb", "R/aquap2.rdx") || !identical(digest::digest(read_raw(file.path(package, entry$path)), algo = "sha256", serialize = FALSE), entry$sha256)) stop("Installed package integrity mismatch.")
  }
  job <- file.path(normalizePath(dirname(args[2]), winslash = "/", mustWork = TRUE), "r-job")
  dir.create(job, showWarnings = FALSE)
  settings <- file.path(job, "settings"); dir.create(settings, showWarnings = FALSE)
  # R_USER must have been isolated by the launcher before process startup.
  home <- normalizePath(path.expand("~"), winslash = "/", mustWork = TRUE)
  qa_prefix <- paste0(normalizePath(file.path(project, "qa"), winslash = "/", mustWork = TRUE), "/v1.6-temperature-")
  if (!startsWith(tolower(home), tolower(qa_prefix))) stop("Use an isolated qa/v1.6-temperature-* R_USER before R starts.")
  Sys.setenv(AQUAP2SH = settings)
  writeLines(paste0("AQUAP2SH = ", settings), file.path(home, ".Renviron"), useBytes = TRUE)
  config <- input$config
  if (!config$coordinateSystem %in% c("ot1.12", "ot1.15")) stop("Invalid coordinate system.")
  stn_env <- new.env()
  sys.source(file.path(project, "qa/aquap2-runtime-v1.4/source/inst/settings.r"), envir = stn_env)
  stn <- stn_env$stn
  stn$allSilent <- TRUE
  stn$aqq_nCoord <- if (config$coordinateSystem == "ot1.12") 12 else 15
  stn$aqg_smoothCalib <- config$calibrationSmoothN
  stn$aqg_tempCalib_forceOutlExcl <- FALSE
  dput(stn, file = file.path(settings, "values.R"))
  lines <- readLines(file.path(settings, "values.R"))
  writeLines(c(paste0("stn <- ", lines[1]), lines[-1]), file.path(settings, "settings.r"))
  suppressPackageStartupMessages(library(aquap2, lib.loc = lib))
  aquap2::updateSettings(silent = TRUE)
  version <- unname(read.dcf(file.path(package, "DESCRIPTION"))[1,"Version"])
  if (version != "0.4.5") stop("Expected aquap2 0.4.5.")
  runtime <<- list(engine = "aquap2", installedPackage = TRUE, aquap2Version = version, rVersion = R.version.string,
    sourceCommit = pin, sourceHarnessUsed = FALSE, packageApiExecuted = FALSE,
    api = "aquap2::gdmm", calibrationApi = I(c("aquap2::ttap", "aquap2::saveAQdata")),
    calibrationOutlierExclusion = FALSE, calibrationSmoothN = stn$aqg_smoothCalib,
    smoothN = config$smoothN, internalMsc = config$msc, coordinateSystem = config$coordinateSystem,
    nrCorr = FALSE, bootCI = FALSE)
  setwd(job); aquap2::genFolderStr()
  x <- numeric_matrix(input$matrix); w <- numeric_array(input$wavelengths)
  cx <- numeric_matrix(input$calibration$matrix); cw <- numeric_array(input$calibration$wavelengths)
  temperatures <- numeric_array(input$calibration$temperatures)
  groups <- enc2utf8(unlist(input$groups, use.names = FALSE))
  if (length(w) != ncol(x) || length(cw) != ncol(cx) || length(temperatures) != nrow(cx) || length(groups) != nrow(x) || any(diff(w) <= 0) || any(diff(cw) <= 0)) stop("Invalid vectors.")
  names <- unique(groups); tokens <- sprintf("G%06d", seq_along(names)); gi <- match(groups, names)
  make_data <- function(matrix, wavelengths, levels, temp, name) {
    n <- nrow(matrix); rows <- sprintf("ROW%07d", seq_len(n))
    header <- data.frame(C_all = factor(rep("all", n)), C_Group = factor(levels), C_ECRM = factor(rep("RM", n)),
      Y_SampleNr = seq_len(n), Y_conSNr = rep(1, n), Y_smpTemp = temp, row.names = rows)
    rownames(matrix) <- rows; colnames(matrix) <- paste0("w", format(wavelengths, scientific = FALSE, trim = TRUE, digits = 17))
    md <- aquap2::getmd(expName = name)
    aquap2::ttap(list(header = header, NIR = matrix), md = md, dol = FALSE, ncpwl = 1, stf = FALSE)
  }
  calibration <- make_data(cx, cw, rep("calibration", nrow(cx)), temperatures, "ArtificialCalibration")
  aquap2::saveAQdata(calibration, aquap2::getmd(expName = "ArtificialCalibration"), verbose = FALSE)
  if (!file.copy(file.path("R-data", "ArtificialCalibration"), file.path(settings, "ArtificialCalibration"))) stop("Calibration copy failed.")
  fd <- make_data(x, w, tokens[gi], rep(config$tExp, nrow(x)), "ArtificialMeasurement")
  reference <- config$reference
  minus <- if (is.null(reference)) NULL else tokens[match(reference, names)]
  targets <- if (is.null(config$targets)) "def" else numeric_array(config$targets)
  tc <- if (is.null(config$tCalib)) NULL else if (is.character(config$tCalib)) config$tCalib else numeric_array(config$tCalib)
  ap <- do.call(aquap2::getap, list(do.pca = FALSE, do.aqg = TRUE, do.pls = FALSE, do.sim = FALSE,
    do.da = FALSE, do.rnf = FALSE, do.svm = FALSE, do.nnet = FALSE,
    spl.var = NULL, spl.wl = NULL, dpt.pre = NULL, dpt.post = NULL,
    spl.do.csAvg = FALSE, spl.do.noise = FALSE, spl.do.exOut = FALSE,
    aqg.vars = "C_Group", aqg.mod = config$mode, aqg.minus = minus, aqg.TCalib = tc, aqg.Texp = config$tExp,
    aqg.smoothN = config$smoothN, aqg.msc = config$msc, aqg.nrCorr = FALSE, aqg.bootCI = FALSE,
    aqg.spectra = FALSE, aqg.selWls = targets))
  cube <- aquap2::gdmm(fd, ap = ap, tempFile = "ArtificialCalibration")
  runtime$packageApiExecuted <<- TRUE
  aq <- aquap2::getcm(cube, 1, what = "aquagr")[[1]]
  if (length(cube) != 1L || !all(is.finite(aq@avg))) stop("Oracle finite-result/single-set guard failed.")
  list(schemaVersion = 1L, ok = TRUE, runtime = runtime,
    result = list(mode = config$mode, labels = I(colnames(aq@avg)), groups = lapply(seq_along(names), function(i)
      list(name = names[i], n = sum(gi == i), values = I(unname(aq@avg[tokens[i], ]))))))
}
sink(stderr(), type = "output")
result <- tryCatch(run(jsonlite::parse_json(rawToChar(read_raw(args[1])), simplifyVector = FALSE)),
  error = function(e) list(schemaVersion = 1L, ok = FALSE, error = list(type = class(e)[1], message = conditionMessage(e)), runtime = runtime))
sink(type = "output")
json <- jsonlite::toJSON(result, auto_unbox = TRUE, digits = NA, null = "null", na = "null", matrix = "rowmajor")
writeBin(charToRaw(paste0(enc2utf8(as.character(json)), "\n")), args[2])
quit(status = if (isTRUE(result$ok)) 0L else 1L)

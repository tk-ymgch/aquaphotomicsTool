#!/usr/bin/env Rscript
# Installed, pinned aquap2 public API. Input is data, never R source.
args <- commandArgs(trailingOnly = TRUE)
file_arg <- grep("^--file=", commandArgs(FALSE), value = TRUE)
script <- normalizePath(sub("^--file=", "", file_arg[1]), winslash = "/", mustWork = TRUE)
project <- dirname(dirname(script))
root <- Sys.getenv("AQUAP2_RUNTIME_ROOT", file.path(project, "qa/aquap2-runtime-v1.4"))
root <- normalizePath(root, winslash = "/", mustWork = FALSE)
lib <- Sys.getenv("AQUAP2_LIBRARY", file.path(root, "library"))
lib <- normalizePath(lib, winslash = "/", mustWork = FALSE)
.libPaths(c(lib, .Library))
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  cat('{"ok":false,"error":{"code":"RUNTIME_UNAVAILABLE","message":"隔離R環境のjsonliteがありません。setup_aquap2.Rを実行してください。"}}\n')
  quit(status = 1L)
}
json <- function(x) jsonlite::toJSON(x, auto_unbox = TRUE, digits = NA, null = "null",
                                    na = "null", matrix = "rowmajor", pretty = FALSE)
write_json <- function(value, output = NULL) {
  text <- enc2utf8(as.character(json(value)))
  if (is.null(output)) cat(text, "\n", sep = "") else writeBin(charToRaw(paste0(text, "\n")), output)
}
input_error <- function(message, code = "UNSUPPORTED_INPUT") {
  stop(structure(list(message = message, call = NULL, code = code),
                 class = c("engine_input_error", "error", "condition")))
}
number <- function(x, label, integer = FALSE) {
  if (!is.numeric(x) || length(x) != 1L || !is.finite(x) ||
      (integer && x != floor(x))) input_error(paste0(label, "は有限の数値で指定してください。"))
  as.numeric(x)
}
numbers <- function(x, label) {
  if (!is.list(x) || !length(x)) input_error(paste0(label, "は数値配列が必要です。"))
  vapply(x, number, numeric(1), label = label, USE.NAMES = FALSE)
}
strings <- function(x, label) {
  if (!is.list(x) || !length(x) || any(!vapply(x, function(s)
      is.character(s) && length(s) == 1L && nzchar(s) && nchar(s, type = "bytes") <= 4096L,
      logical(1)))) input_error(paste0(label, "は空でない文字列の配列が必要です。"))
  enc2utf8(unlist(x, use.names = FALSE))
}
load_runtime <- function() {
  if (!dir.exists(lib)) input_error("隔離aquap2ライブラリがありません。", "RUNTIME_UNAVAILABLE")
  package <- tryCatch(find.package("aquap2", lib.loc = lib), error = function(e) "")
  if (!nzchar(package)) input_error("aquap2が隔離ライブラリに導入されていません。", "RUNTIME_UNAVAILABLE")
  receipt_file <- file.path(root, "installation.json")
  if (!file.exists(receipt_file)) input_error("固定版の導入証跡がありません。setup_aquap2.Rを実行してください。", "RUNTIME_UNAVAILABLE")
  receipt <- jsonlite::parse_json(paste(readLines(receipt_file, warn = FALSE, encoding = "UTF-8"), collapse = "\n"))
  commit <- "d31c1231bf71f0e73f1a630a32934602782be488"
  if (!identical(receipt$sourceCommit, commit) ||
      !identical(receipt$sourceArchiveSha256, "22e6582a7205a723f0f70e3e3c91db272f3eefcb4eabb29023a9229091df0130")) {
    input_error("固定版aquap2の導入証跡が一致しません。", "RUNTIME_UNAVAILABLE")
  }
  if (!requireNamespace("digest", quietly = TRUE)) input_error("digestがありません。", "RUNTIME_UNAVAILABLE")
  for (entry in receipt$installedFiles) {
    if (!entry$path %in% c("DESCRIPTION", "NAMESPACE", "R/aquap2.rdb", "R/aquap2.rdx") ||
        !file.exists(file.path(package, entry$path)) ||
        digest::digest(readBin(file.path(package, entry$path), "raw",
          n = file.info(file.path(package, entry$path))$size), serialize = FALSE, algo = "sha256") != entry$sha256) {
      input_error("導入済みaquap2の整合性検査に失敗しました。", "RUNTIME_UNAVAILABLE")
    }
  }
  if (length(receipt$installedFiles) != 4L) input_error("導入証跡が不完全です。", "RUNTIME_UNAVAILABLE")
  suppressPackageStartupMessages(library(aquap2, lib.loc = lib, character.only = FALSE))
  version <- unname(read.dcf(file.path(package, "DESCRIPTION"))[1, "Version"])
  if (version != "0.4.5") input_error("対応するaquap2は固定版0.4.5です。", "RUNTIME_UNAVAILABLE")
  list(engine = "aquap2", aquap2Version = version, rVersion = R.version.string,
       installedPackage = TRUE, sourceCommit = commit,
       sourceArchiveSha256 = receipt$sourceArchiveSha256,
       packageApiExecuted = FALSE, api = "aquap2::gdmm",
       preprocessing = "provided-matrix-identity-sg3-msc-off; PCA-mean-centered-unscaled",
       identitySG = list(window = 3L, polyorder = 2L, derivative = 0L,
                         requestedBecauseNullRejected = TRUE),
       aquagramSdDdof = 1L, pcaCenter = TRUE, pcaScale = FALSE,
       getters = I(c("aquap2::getcm(cube,1,'pca')$model", "aquap2::getcm(cube,1,'aquagr')[[1]]@avg")))
}
analyze <- function(input, runtime) {
  if (!is.list(input) || !identical(input$schemaVersion, 1L) && !identical(input$schemaVersion, 1)) {
    input_error("schemaVersionは1が必要です。")
  }
  if (!is.null(input$pls)) input_error("aquap2方式ではPLSを実行しません。PLS設定を無効にしてください。")
  wls <- numbers(input$wavelengths, "波長")
  ids <- strings(input$ids, "試料ID")
  groups <- strings(input$groups, "群")
  n <- length(ids); p <- length(wls)
  if (n < 2L || p < 3L || p > 10000L || n * p > 2000000L || min(n, p) > 1000L) {
    input_error("R解析は2試料以上・3～10000波長、200万要素以下、行列の短辺1000以下にしてください。")
  }
  if (length(groups) != n || anyDuplicated(ids) || any(wls <= 0) || any(diff(wls) <= 0)) {
    input_error("IDは一意、群の数は試料数と一致、波長は正で昇順・重複なしにしてください。")
  }
  if (!is.list(input$matrix) || length(input$matrix) != n ||
      any(vapply(input$matrix, length, integer(1)) != p)) input_error("行列の形状が試料数・波長数と一致しません。")
  x <- do.call(rbind, lapply(input$matrix, numbers, label = "スペクトル"))
  if (any(rowSums(abs(x)) == 0)) input_error("aquap2が除去する全波長0の試料行があります。試料を確認してください。")
  if (!is.list(input$pca) || !identical(input$pca$scale, FALSE)) {
    input_error("aquap2 PCAは平均中心化のみです。PCAスケーリングをOFFにしてください。")
  }
  k <- number(input$pca$components, "PCA成分数", integer = TRUE)
  if (k < 1L || k > 10L || k > min(n - 1L, p)) input_error("PCA成分数は1～10、試料数−1と波長数以下にしてください。")
  if (!is.list(input$aquagram)) input_error("Aquagram設定がありません。")
  targets <- numbers(input$aquagram$wavelengths, "Aquagram実波長")
  if (length(targets) < 2L || length(targets) > 24L || anyDuplicated(targets) ||
      any(!targets %in% wls) || any(diff(targets) <= 0)) {
    input_error("Aquagramは実際の波長列と完全一致する2～24波長を昇順・重複なしで指定してください。")
  }
  reference <- input$aquagram$reference
  if (!is.character(reference) || length(reference) != 1L) input_error("Aquagram基準を指定してください。")
  control <- NULL
  if (identical(reference, "global")) mode <- "classic" else if (startsWith(reference, "group:")) {
    control <- substring(reference, 7L)
    if (!control %in% groups) input_error("Aquagram対照群が見つかりません。")
    mode <- "classic-diff"
  } else input_error("aquap2は全体平均または対照群のみ対応します。基準なし・AUC温度校正は未対応です。")
  if (!is.null(input$aquagram$mode) && !identical(input$aquagram$mode, mode)) {
    input_error("Aquagram modeと基準が一致しません。")
  }
  # R_USER must be set before R starts, so aquap2 cannot create user-home files.
  expected_home <- normalizePath(file.path(root, "home"), winslash = "/", mustWork = TRUE)
  actual_home <- normalizePath(Sys.getenv("HOME"), winslash = "/", mustWork = TRUE)
  if (!identical(tolower(actual_home), tolower(expected_home))) {
    input_error("R起動前にR_USERを隔離runtimeのhomeへ設定してください。", "RUNTIME_UNAVAILABLE")
  }
  settings <- file.path(root, "settings")
  dir.create(settings, recursive = TRUE, showWarnings = FALSE)
  Sys.setenv(AQUAP2SH = settings)
  writeLines(paste0("AQUAP2SH = ", settings), file.path(expected_home, ".Renviron"), useBytes = TRUE)
  aquap2::updateSettings(silent = TRUE)
  jobs <- file.path(root, "jobs"); dir.create(jobs, showWarnings = FALSE)
  job <- tempfile("request-", tmpdir = jobs); dir.create(job)
  keep_evidence <- identical(Sys.getenv("AQUAP2_KEEP_EVIDENCE"), "1")
  old_wd <- getwd()
  # Normal requests retain no matrix/cube. Only explicit operator opt-in keeps
  # artificial comparison evidence. Verify the resolved target before deletion.
  cleanup_job <- function() {
    setwd(old_wd)
    target <- normalizePath(job, winslash = "/", mustWork = FALSE)
    parent <- paste0(normalizePath(jobs, winslash = "/", mustWork = TRUE), "/")
    if (!keep_evidence && startsWith(tolower(target), tolower(parent)) &&
        startsWith(basename(target), "request-")) unlink(target, recursive = TRUE, force = TRUE)
  }
  on.exit(cleanup_job(), add = TRUE)
  setwd(job)
  aquap2::genFolderStr()
  md <- aquap2::getmd(expName = "Workbench-preprocessed-matrix")
  # Only synthetic internal row/group tokens enter aquap2. Original labels stay
  # in the JSON result and cannot collide with aquap2's reserved class columns.
  row_tokens <- sprintf("WB_%07d", seq_len(n))
  group_names <- unique(groups)
  group_tokens <- sprintf("G%06d", seq_along(group_names))
  group_index <- match(groups, group_names)
  header <- data.frame(C_all = factor(rep("all", n)),
                       C_Group = factor(group_tokens[group_index], levels = group_tokens),
                       C_ECRM = factor(rep("RM", n)),
                       Y_SampleNr = seq_len(n), Y_conSNr = rep(1, n), row.names = row_tokens)
  colnames(x) <- paste0("w", format(wls, scientific = FALSE, trim = TRUE, digits = 17))
  rownames(x) <- row_tokens
  fd <- aquap2::ttap(list(header = header, NIR = x), md = md, dol = FALSE, ncpwl = 1, stf = FALSE)
  ap <- do.call(aquap2::getap, list(do.pca = TRUE, do.aqg = TRUE, do.pls = FALSE, do.sim = FALSE,
    do.da = FALSE, do.rnf = FALSE, do.svm = FALSE, do.nnet = FALSE,
    spl.var = NULL, spl.wl = NULL, dpt.pre = NULL, dpt.post = NULL,
    spl.do.csAvg = FALSE, spl.do.noise = FALSE, spl.do.exOut = FALSE,
    aqg.vars = "C_Group", aqg.mod = mode,
    aqg.minus = if (is.null(control)) NULL else group_tokens[match(control, group_names)],
    aqg.smoothN = 3, aqg.msc = FALSE, aqg.nrCorr = FALSE, aqg.bootCI = FALSE,
    aqg.spectra = FALSE, aqg.selWls = targets))
  cube <- aquap2::gdmm(fd, ap = ap)
  if (length(cube) != 1L) stop("Unexpected split count from aquap2.")
  used <- aquap2::getcd(cube, 1)
  if (!identical(rownames(used$NIR), row_tokens) || !identical(dim(used$NIR), dim(x)) ||
      !identical(as.numeric(used$NIR), as.numeric(x))) {
    if (keep_evidence) saveRDS(list(input = x, used = used, rowTokens = row_tokens), file.path(job, "dataset-check.rds"))
    stop("aquap2 dataset changed before model calculation.")
  }
  model <- aquap2::getcm(cube, 1, what = "pca")$model
  aq <- aquap2::getcm(cube, 1, what = "aquagr")[[1]]
  avg <- aq@avg
  if (!setequal(rownames(avg), group_tokens) || ncol(avg) != length(targets) ||
      any(!is.finite(avg)) || any(!is.finite(model$scores)) || any(!is.finite(model$loadings)) ||
      !is.finite(model$totalvar) || model$totalvar <= 0) {
    input_error("R計算に非有限値が生じました。定数のAquagram列や変動のない行列を確認してください。")
  }
  # The public API rejects NULL smoothing in 0.4.5. Record the exact unavoidable
  # identity call and measure its floating-point effect on this request.
  identity <- t(apply(x, 1, signal::sgolayfilt, p = 2, n = 3, m = 0))
  identity_error <- max(abs(identity - x))
  runtime$identitySG$maximumAbsoluteEffect <- identity_error
  runtime$identitySG$withinFloatingPointTolerance <- identity_error <= 1e-12 * max(1, max(abs(x)))
  if (!runtime$identitySG$withinFloatingPointTolerance) stop("Identity SG exceeded numerical tolerance.")
  runtime$packageApiExecuted <- TRUE
  runtime$inputSamples <- n; runtime$inputVariables <- p
  runtime$aquagramMode <- mode
  runtime$datasetClass <- class(fd)[1]; runtime$cubeClass <- class(cube)[1]
  runtime$pcaModelClass <- class(model)[1]; runtime$aquagramClass <- class(aq)[1]
  runtime$analysis <- list(extraDataPreprocessing = FALSE, consecutiveScanAveraging = FALSE,
    noise = FALSE, outlierDetection = FALSE, observationBalancing = FALSE, bootstrap = FALSE,
    aquagramMSC = FALSE, aquagramSmoothN = 3L, pca = "mean-centered-unscaled")
  if (keep_evidence) saveRDS(list(metadata = md, analysis = ap, settings = .GlobalEnv$.ap2$stn,
    dataset = fd, cube = cube, runtime = runtime), file.path(job, "api-evidence.rds"))
  definition <- if (mode == "classic")
    "aquap2 classic: 各実波長で全試料を平均中心化・標本SD(ddof=1)で標準化して群平均。" else
    "aquap2 classic-diff: classicの標準化群平均から指定対照群を減算（標本SD ddof=1）。"
  list(schemaVersion = 1L, ok = TRUE,
    pca = list(scores = unname(model$scores[, seq_len(k), drop = FALSE]),
      loadings = unname(model$loadings[, seq_len(k), drop = FALSE]),
      explainedVariance = I(unname(model$var[seq_len(k)] / model$totalvar)),
      ids = I(ids), groups = I(groups)),
    aquagram = list(wavelengths = I(targets), labels = I(paste0(targets, " nm")),
      groups = lapply(seq_along(group_names), function(i) list(name = group_names[i],
        values = I(unname(avg[group_tokens[i], ])), n = sum(group_index == i))),
      reference = if (is.null(control)) "全体平均" else paste0("対照群: ", control),
      definition = definition, mode = mode, ddof = 1L),
    runtime = runtime,
    warnings = I("aquap2 0.4.5の公開API制約によりAquagram内部で3点2次の恒等SGを呼び出し、その丸め差を記録しました。温度校正・AUC・PLSは実行していません。"))
}
health <- identical(args, "--health")
output <- if (!health && length(args) == 2L) args[2] else NULL
sink(stderr(), type = "output")
result <- tryCatch({
  runtime <- load_runtime()
  if (health) list(schemaVersion = 1L, ok = TRUE, runtime = runtime,
    capabilities = list(pca = TRUE, pcaScale = FALSE,
      aquagramModes = I(c("classic", "classic-diff")), pls = FALSE, temperatureCalibration = FALSE),
    limits = list(maxElements = 2000000L, maxVariables = 10000L, maxShortDimension = 1000L)) else {
    if (length(args) != 2L) input_error("Usage: Rscript aquap2_engine.R input.json output.json")
    size <- file.info(args[1])$size
    if (!is.finite(size) || size <= 0 || size > 64 * 1024^2) input_error("入力JSONは64 MiB以下にしてください。")
    input <- jsonlite::parse_json(readChar(args[1], nchars = size, useBytes = TRUE), simplifyVector = FALSE)
    analyze(input, runtime)
  }
}, error = function(e) {
  message(conditionMessage(e))
  list(schemaVersion = 1L, ok = FALSE, error = list(
    code = if (inherits(e, "engine_input_error")) e$code else "R_ENGINE_FAILURE",
    message = if (inherits(e, "engine_input_error")) conditionMessage(e) else
      "aquap2本体の実行に失敗しました。ローカルRログを確認してください。"))
})
sink(type = "output")
write_json(result, output)
quit(status = if (isTRUE(result$ok)) 0L else 1L)

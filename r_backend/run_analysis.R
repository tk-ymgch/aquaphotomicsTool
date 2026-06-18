args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 3) {
  stop("Usage: Rscript run_analysis.R input.csv config.txt output_dir")
}

input_file <- args[[1]]
config_file <- args[[2]]
output_dir <- args[[3]]
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

local_lib <- Sys.getenv("AQUA_R_LIBS", file.path(getwd(), "r_libs"))
dir.create(local_lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(normalizePath(local_lib, mustWork = FALSE), .libPaths()))

aquap2_available <- suppressWarnings(requireNamespace("aquap2", quietly = TRUE))
aquap2_version <- "not-installed"
if (aquap2_available) {
  aquap2_version <- as.character(utils::packageVersion("aquap2"))
}

read_config <- function(path) {
  lines <- readLines(path, warn = FALSE)
  lines <- lines[nzchar(trimws(lines))]
  res <- list()
  for (line in lines) {
    pos <- regexpr("=", line, fixed = TRUE)[[1]]
    if (pos < 1) next
    key <- substr(line, 1, pos - 1)
    value <- substr(line, pos + 1, nchar(line))
    res[[key]] <- utils::URLdecode(value)
  }
  res
}

split_values <- function(x) {
  if (is.null(x) || !nzchar(x)) return(character(0))
  utils::URLdecode(unlist(strsplit(x, "|", fixed = TRUE), use.names = FALSE))
}

safe_num <- function(x, default = 0) {
  v <- suppressWarnings(as.numeric(x))
  if (length(v) == 0 || is.na(v)) default else v
}

fill_matrix <- function(x) {
  x <- as.matrix(x)
  storage.mode(x) <- "numeric"
  for (j in seq_len(ncol(x))) {
    col <- x[, j]
    if (all(is.na(col))) {
      x[, j] <- 0
    } else {
      m <- mean(col, na.rm = TRUE)
      col[is.na(col)] <- m
      x[, j] <- col
    }
  }
  x
}

snv <- function(x) {
  t(apply(x, 1, function(row) {
    s <- stats::sd(row, na.rm = TRUE)
    if (is.na(s) || s == 0) s <- 1
    (row - mean(row, na.rm = TRUE)) / s
  }))
}

msc <- function(x) {
  ref <- colMeans(x, na.rm = TRUE)
  t(apply(x, 1, function(row) {
    fit <- tryCatch(stats::lm(row ~ ref), error = function(e) NULL)
    if (is.null(fit)) return(row)
    co <- stats::coef(fit)
    slope <- co[[2]]
    if (is.na(slope) || slope == 0) slope <- 1
    (row - co[[1]]) / slope
  }))
}

smooth_vec <- function(v, k) {
  n <- length(v)
  if (k < 3 || k > n) return(v)
  if (k %% 2 == 0) k <- k + 1
  half <- floor(k / 2)
  out <- numeric(n)
  for (i in seq_len(n)) {
    lo <- max(1, i - half)
    hi <- min(n, i + half)
    out[i] <- mean(v[lo:hi], na.rm = TRUE)
  }
  out
}

smooth_matrix <- function(x, k) {
  t(apply(x, 1, smooth_vec, k = k))
}

cfg <- read_config(config_file)
wl_cols <- split_values(cfg[["wavelength_cols"]])
wl_values <- suppressWarnings(as.numeric(split_values(cfg[["wavelength_values"]])))
aquagram_values <- suppressWarnings(as.numeric(split_values(cfg[["aquagram_values"]])))

if (length(wl_cols) < 3) {
  stop("At least three wavelength columns are required.")
}

df <- utils::read.csv(input_file, check.names = FALSE, stringsAsFactors = FALSE)
missing_cols <- setdiff(wl_cols, names(df))
if (length(missing_cols) > 0) {
  stop("Missing wavelength columns: ", paste(missing_cols, collapse = ", "))
}

sample_col <- cfg[["sample_col"]]
group_col <- cfg[["group_col"]]
scatter <- cfg[["scatter"]]
if (is.null(scatter) || !nzchar(scatter)) scatter <- "None"
sg_window <- as.integer(safe_num(cfg[["sg_window"]], 7))
derivative <- as.integer(safe_num(cfg[["derivative"]], 0))
reference_mode <- cfg[["reference_mode"]]
control_group <- cfg[["control_group"]]

x <- fill_matrix(df[, wl_cols, drop = FALSE])
wl <- wl_values
if (length(wl) != ncol(x) || any(is.na(wl))) wl <- seq_len(ncol(x))

if (sg_window >= 3) {
  if (sg_window %% 2 == 0) sg_window <- sg_window + 1
  x <- smooth_matrix(x, min(sg_window, ncol(x)))
}

if (derivative > 0) {
  derivative <- min(derivative, 2)
  for (d in seq_len(derivative)) {
    x <- t(apply(x, 1, diff))
    wl <- (wl[-1] + wl[-length(wl)]) / 2
  }
}

if (identical(scatter, "SNV")) x <- snv(x)
if (identical(scatter, "MSC")) x <- msc(x)

sample_id <- if (!is.null(sample_col) && nzchar(sample_col) && sample_col %in% names(df)) as.character(df[[sample_col]]) else paste0("S", seq_len(nrow(df)))
groups <- if (!is.null(group_col) && nzchar(group_col) && group_col %in% names(df)) as.character(df[[group_col]]) else rep("All samples", nrow(df))

processed_names <- paste0("wl_", format(round(wl, 4), trim = TRUE, scientific = FALSE))
processed <- data.frame(sample_id = sample_id, group = groups, x, check.names = FALSE)
names(processed) <- c("sample_id", "group", processed_names)

ncomp <- min(5, nrow(x) - 1, ncol(x))
if (ncomp >= 2) {
  pca <- stats::prcomp(x, center = TRUE, scale. = FALSE)
  scores <- as.data.frame(pca$x[, seq_len(ncomp), drop = FALSE])
  scores <- data.frame(sample_id = sample_id, group = groups, scores, check.names = FALSE)
  loadings <- as.data.frame(pca$rotation[, seq_len(ncomp), drop = FALSE])
  loadings <- data.frame(wavelength = wl, loadings, check.names = FALSE)
  variance <- data.frame(component = paste0("PC", seq_len(ncomp)), explained_variance = (pca$sdev[seq_len(ncomp)]^2) / sum(pca$sdev^2))
} else {
  scores <- data.frame(sample_id = sample_id, group = groups, PC1 = numeric(length(sample_id)), PC2 = numeric(length(sample_id)))
  loadings <- data.frame(wavelength = wl, PC1 = numeric(length(wl)), PC2 = numeric(length(wl)))
  variance <- data.frame(component = c("PC1", "PC2"), explained_variance = c(NA, NA))
}

if (length(aquagram_values) < 3 || any(is.na(aquagram_values))) {
  aquagram_values <- stats::quantile(wl, probs = seq(0.05, 0.95, length.out = min(12, length(wl))), names = FALSE)
}
positions <- vapply(aquagram_values, function(v) which.min(abs(wl - v)), integer(1))
positions <- unique(positions)
aq_wl <- wl[positions]
aq_x <- x[, positions, drop = FALSE]

if (identical(reference_mode, "Control group") && !is.null(control_group) && nzchar(control_group) && any(groups == control_group)) {
  ref <- colMeans(aq_x[groups == control_group, , drop = FALSE], na.rm = TRUE)
} else if (identical(reference_mode, "None")) {
  ref <- rep(0, ncol(aq_x))
} else {
  ref <- colMeans(aq_x, na.rm = TRUE)
}
scale_vec <- apply(aq_x, 2, stats::sd, na.rm = TRUE)
scale_vec[is.na(scale_vec) | scale_vec == 0] <- 1

aquagram <- do.call(rbind, lapply(unique(groups), function(g) {
  m <- colMeans(aq_x[groups == g, , drop = FALSE], na.rm = TRUE)
  if (identical(reference_mode, "None")) {
    values <- m
  } else {
    values <- (m - ref) / scale_vec
  }
  data.frame(group = g, wavelength = aq_wl, value = values, check.names = FALSE)
}))

processed_csv <- file.path(output_dir, "processed_spectra.csv")
scores_csv <- file.path(output_dir, "pca_scores.csv")
loadings_csv <- file.path(output_dir, "pca_loadings.csv")
variance_csv <- file.path(output_dir, "pca_variance.csv")
aquagram_csv <- file.path(output_dir, "aquagram.csv")
utils::write.csv(processed, processed_csv, row.names = FALSE)
utils::write.csv(scores, scores_csv, row.names = FALSE)
utils::write.csv(loadings, loadings_csv, row.names = FALSE)
utils::write.csv(variance, variance_csv, row.names = FALSE)
utils::write.csv(aquagram, aquagram_csv, row.names = FALSE)

cat(paste(
  "RESULT",
  normalizePath(processed_csv),
  normalizePath(scores_csv),
  normalizePath(loadings_csv),
  normalizePath(variance_csv),
  normalizePath(aquagram_csv),
  aquap2_available,
  aquap2_version,
  sep = "|"
), "\n")

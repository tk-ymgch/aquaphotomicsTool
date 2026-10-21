#!/usr/bin/env Rscript
# Limited source harness, NOT an installed aquap2/API integration test.
# See docs/AQUAP2_COMPARISON.md for provenance, adapters and exclusions.
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 4L) {
  stop(paste("Usage: Rscript scripts/aquap2_reference.R <pinned-source-dir>",
             "<data/preprocessed.csv> <data/aquagram.csv> <new-output-dir>"), call. = FALSE)
}
source_dir <- normalizePath(args[1], winslash = "/", mustWork = TRUE)
input_csv <- normalizePath(args[2], winslash = "/", mustWork = TRUE)
expected_csv <- normalizePath(args[3], winslash = "/", mustWork = TRUE)
output_dir <- args[4]
if (file.exists(output_dir) || dir.exists(output_dir)) stop("Output must be a new directory.")

# Exact UTF-8/LF bytes obtained from immutable upstream commits. MD5 here guards
# accidental source replacement; upstream Git blob and SHA-256 are in evidence.
source_md5 <- c(calc_aqg.r = "41a587e9dad8a045bfe0cfc5c082bfaf",
                gen_coreDataManip.r = "5454d0c739f5165bc70f72dc9d5587bc",
                som.R = "9c2f27f873bc21ae4fe93f95d05b5e6d")
paths <- file.path(source_dir, names(source_md5))
if (!all(file.exists(paths)) || !identical(unname(tools::md5sum(paths)), unname(source_md5))) {
  stop("Pinned source missing or bytes differ. Download the exact files listed in the guide.")
}

# No whole-file source(), package initialization, arbitrary expressions, network
# or package installation. Only allowlisted function assignments are evaluated.
pick_function <- function(path, name) {
  expressions <- parse(file = path, encoding = "UTF-8", keep.source = FALSE)
  matches <- Filter(function(x) is.call(x) && length(x) == 3L &&
                      identical(x[[1]], as.name("<-")) && identical(x[[2]], as.name(name)),
                    as.list(expressions))
  if (length(matches) != 1L || !is.call(matches[[1]][[3]]) ||
      !identical(matches[[1]][[3]][[1]], as.name("function"))) {
    stop(paste("Expected exactly one function assignment:", name))
  }
  matches[[1]][[3]]
}
ref <- new.env(parent = baseenv())
ref$source_normalize <- eval(pick_function(paths[3], "normalize"), envir = ref)
scale_node <- pick_function(paths[2], "do_scale")
# Explicit namespace adapter: use the unchanged pinned som normalize function
# without requiring its unrelated compiled SOM algorithm. Only one call changes.
replacement_count <- 0L
bind_som <- function(x) {
  if (!is.call(x)) return(x)
  if (identical(x[[1]], quote(som::normalize))) {
    x[[1]] <- as.name("source_normalize")
    replacement_count <<- replacement_count + 1L
  }
  if (length(x) > 1L) for (i in seq.int(2L, length(x))) x[[i]] <- bind_som(x[[i]])
  x
}
scale_node <- bind_som(scale_node)
if (replacement_count != 1L) stop("Unexpected source namespace call count.")
ref$do_scale <- eval(scale_node, envir = ref)
# Explicit group-mean adapter for plyr::ddply: finite complete data, factor levels
# all observed, fixed order. This does NOT test plyr or official do_ddply itself.
ref$do_ddply <- function(dataset, colInd) {
  g <- dataset$header[, colInd]
  out <- t(vapply(levels(g), function(level) colMeans(dataset$NIR[g == level, , drop = FALSE]),
                  numeric(ncol(dataset$NIR))))
  rownames(out) <- levels(g)
  colnames(out) <- colnames(dataset$NIR)
  as.data.frame(out, check.names = FALSE)
}
for (name in c("aquCoreCalc_Classic", "aquCoreCalc_Classic_diff")) {
  assign(name, eval(pick_function(paths[1], name), envir = ref), envir = ref)
}

read_chars <- function(path) {
  size <- file.info(path)$size
  if (!is.finite(size) || size > 100 * 1024^2) stop("CSV must be at most 100 MiB.")
  read.csv(path, check.names = FALSE, fileEncoding = "UTF-8-BOM",
           colClasses = "character", na.strings = character(0))
}
as_finite <- function(x) {
  out <- suppressWarnings(as.numeric(x))
  if (any(!is.finite(out))) stop("Missing or non-finite numeric value.")
  out
}
df <- read_chars(input_csv)
expected <- read_chars(expected_csv)
if (anyDuplicated(names(df)) || !all(c("sample_id", "group") %in% names(df))) {
  stop("Preprocessed CSV needs unique columns including sample_id and group.")
}
wl_cols <- names(df)[grepl("^wl_[0-9]+([.][0-9]+)?$", names(df))]
if (length(wl_cols) < 3L || length(wl_cols) > 10000L || nrow(df) < 2L ||
    nrow(df) * length(wl_cols) > 2000000L) stop("Unsupported matrix dimensions.")
if (anyDuplicated(df$sample_id) || any(!nzchar(df$sample_id)) || any(!nzchar(df$group))) {
  stop("Unique non-empty sample IDs and non-empty groups are required.")
}
wls <- as_finite(sub("^wl_", "", wl_cols))
if (any(wls <= 0) || any(diff(wls) <= 0)) stop("Wavelengths must be positive and increasing.")
x <- vapply(df[wl_cols], as_finite, numeric(nrow(df)))
if (any(apply(x, 2L, sd) <= 0)) stop("Constant columns are outside this source comparison.")
group_levels <- sort(unique(df$group), method = "radix")
header <- data.frame(C_Group = factor(df$group, levels = group_levels))
dataset <- list(header = header, NIR = x)
if (!all(c("group", "n", "wavelength_nm", "value") %in% names(expected))) {
  stop("Expected Workbench export columns: group,n,wavelength_nm,value.")
}
expected_wls <- as_finite(expected$wavelength_nm)
if (length(setdiff(unique(expected_wls), wls)) ||
    !setequal(unique(expected$group), group_levels)) stop("Expected group/wavelength mismatch.")
selected <- which(wls %in% unique(expected_wls))
expected_matrix <- matrix(NA_real_, nrow = length(group_levels), ncol = length(selected),
                          dimnames = list(group_levels, as.character(wls[selected])))
for (i in seq_len(nrow(expected))) {
  row <- match(expected$group[i], group_levels)
  column <- match(expected_wls[i], wls[selected])
  if (is.finite(expected_matrix[row, column])) stop("Duplicate expected coordinate.")
  expected_matrix[row, column] <- as_finite(expected$value[i])
  if (as_finite(expected$n[i]) != sum(df$group == expected$group[i])) stop("Group size mismatch.")
}
if (any(!is.finite(expected_matrix))) stop("Expected coordinates are incomplete.")
if (length(selected) < 2L) stop("At least two selected coordinates are required by this harness.")

# Operate on already preprocessed spectra. Disable aquap2's additional SG/MSC.
# This excludes its full dataset preparation, cleaning, balancing and calibration.
classic <- as.matrix(ref$aquCoreCalc_Classic(dataset, smoothN = NULL,
                    reference = NULL, msc = FALSE, selIndsWL = selected, colInd = 1L, apLoc = NULL))
minus <- group_levels[1]
classic_diff <- as.matrix(ref$aquCoreCalc_Classic_diff(dataset, smoothN = NULL,
                         reference = NULL, msc = FALSE, selIndsWL = selected,
                         colInd = 1L, minus = minus, apLoc = NULL))
sample_factor <- sqrt((nrow(x) - 1) / nrow(x))
expected_classic <- expected_matrix * sample_factor
expected_diff <- sweep(expected_classic, 2L, expected_classic[minus, ], "-")
max_classic_error <- max(abs(classic - expected_classic))
max_diff_error <- max(abs(classic_diff - expected_diff))
tolerance <- 1e-12
if (max_classic_error > tolerance || max_diff_error > tolerance) {
  stop("Source comparison failed. Input must use Workbench global-mean/population-SD values.")
}
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
if (!dir.exists(output_dir)) stop("Could not create output directory.")
write.csv(classic, file.path(output_dir, "classic-source.csv"), fileEncoding = "UTF-8")
write.csv(classic_diff, file.path(output_dir, "classic-diff-source.csv"), fileEncoding = "UTF-8")
report <- list(status = "limited-source-harness-pass", package_api_executed = FALSE,
               aquap2_version = "0.4.5", aquap2_commit = "d31c1231bf71f0e73f1a630a32934602782be488",
               som_commit = "a56214b9583cea8e4f2856d28d9461072ec3d20c", R = R.version.string,
               adapters = c("som namespace bound to pinned pure-R normalize",
                            "do_ddply substituted by base-R finite-data factor group mean"),
               samples = nrow(x), groups = group_levels, coordinates = wls[selected],
               sample_sd_factor = sample_factor, comparisons = 2L * length(classic),
               maximum_classic_error = max_classic_error, maximum_classic_diff_error = max_diff_error,
               tolerance = tolerance,
               source_md5 = as.list(source_md5),
               input_md5 = unname(tools::md5sum(input_csv)),
               expected_md5 = unname(tools::md5sum(expected_csv)),
               exclusions = c("installed aquap2/gdmm API", "SG and MSC", "temperature calibration",
                              "AUC modes", "real measurements", "near-limit data", "bootstrap"))
saveRDS(report, file.path(output_dir, "source-comparison.rds"))
capture.output(dput(report), file = file.path(output_dir, "source-comparison.txt"))
cat("Limited source harness passed; installed aquap2/API comparison NOT performed.\n")
cat("Comparisons:", report$comparisons, "maximum errors:", max_classic_error, max_diff_error, "\n")

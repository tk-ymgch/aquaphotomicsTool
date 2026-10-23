#!/usr/bin/env Rscript
# Import a Workbench result into an ordinary base-R list; this is not aquap_data.
# Rscript r/r_import.R <extracted-result-root> <new-output.rds>
# No package installation, network requests, eval, or sourcing user-supplied code.

abort <- function(message) stop(message, call. = FALSE)

import_workbench <- function(root_argument, output_argument) {
  if (!nzchar(root_argument) || !dir.exists(root_argument)) {
    abort("The extracted result root must be an existing directory.")
  }
  root <- normalizePath(root_argument, winslash = "/", mustWork = TRUE)
  input <- file.path(root, "data", "preprocessed.csv")
  if (!file.exists(input) || isTRUE(file.info(input)$isdir)) {
    abort("data/preprocessed.csv was not found under the extracted result root.")
  }
  input <- normalizePath(input, winslash = "/", mustWork = TRUE)
  prefix <- paste0(sub("/+$", "", root), "/")
  inside <- if (.Platform$OS.type == "windows") {
    startsWith(tolower(input), tolower(prefix))
  } else startsWith(input, prefix)
  if (!inside) abort("The input CSV resolves outside the extracted result root.")
  input_size <- file.info(input)$size
  if (!is.finite(input_size) || input_size <= 0 || input_size > 100 * 1024^2) {
    abort("The input CSV must be nonempty and no larger than 100 MiB.")
  }
  if (!nzchar(output_argument) || dir.exists(output_argument) || file.exists(output_argument)) {
    abort("Choose a new output .rds path; existing files are never overwritten.")
  }
  if (!grepl("\\.rds$", output_argument, ignore.case = TRUE)) {
    abort("The output filename must end in .rds.")
  }
  output_parent <- dirname(output_argument)
  if (!dir.exists(output_parent)) abort("The output directory must already exist.")
  output_parent <- normalizePath(output_parent, winslash = "/", mustWork = TRUE)
  output <- file.path(output_parent, basename(output_argument))

  # Read all fields as text first to preserve IDs such as 001 and the literal NA.
  # Numeric conversion below validates every spectral cell without evaluating it.
  table <- read.csv(input, check.names = FALSE, fileEncoding = "UTF-8-BOM",
                    colClasses = "character", stringsAsFactors = FALSE,
                    row.names = NULL, na.strings = character(0), comment.char = "",
                    blank.lines.skip = FALSE)
  if (!nrow(table)) abort("The CSV contains no samples.")
  if (anyNA(names(table)) || any(!nzchar(names(table))) || anyDuplicated(names(table))) {
    abort("Column names must be nonempty and unique.")
  }
  required <- c("sample_id", "group")
  if (!all(required %in% names(table))) abort("sample_id and group columns are required.")
  wavelength_columns <- names(table)[startsWith(names(table), "wl_")]
  if (length(wavelength_columns) < 3L || length(wavelength_columns) > 10000L) {
    abort("The CSV must contain between 3 and 10000 wl_ spectral columns.")
  }
  unexpected <- setdiff(names(table), c(required, wavelength_columns))
  if (length(unexpected)) abort("Unexpected columns: use data/preprocessed.csv, not data/input.csv.")
  if (as.double(nrow(table)) * length(wavelength_columns) > 2000000) {
    abort("The spectral matrix exceeds the 2000000-element limit.")
  }
  labels <- sub("^wl_", "", wavelength_columns)
  numeric_label <- "^[+]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
  if (any(!grepl(numeric_label, labels, perl = TRUE))) abort("A wl_ column has an invalid numeric wavelength.")
  wavelengths <- suppressWarnings(as.numeric(labels))
  if (any(!is.finite(wavelengths)) || any(wavelengths <= 0) ||
      anyDuplicated(wavelengths) || any(diff(wavelengths) <= 0)) {
    abort("Wavelengths must be finite, positive, unique and increasing, in nm.")
  }
  ids <- table[["sample_id"]]
  groups <- table[["group"]]
  if (anyNA(ids) || any(!nzchar(trimws(ids))) || anyDuplicated(ids)) {
    abort("sample_id values must be nonempty and unique.")
  }
  if (anyNA(groups) || any(!nzchar(trimws(groups)))) abort("group values must be nonempty.")
  numeric_columns <- lapply(table[wavelength_columns], function(values) {
    converted <- suppressWarnings(as.numeric(values))
    if (any(!is.finite(converted))) abort("A spectral cell is empty, nonnumeric, NaN or infinite.")
    converted
  })
  spectra <- matrix(unlist(numeric_columns, use.names = FALSE),
                    nrow = nrow(table), ncol = length(wavelength_columns),
                    dimnames = list(ids, labels))
  storage.mode(spectra) <- "double"
  header <- data.frame(sample_id = ids, group = groups,
                       stringsAsFactors = FALSE, check.names = FALSE)
  rownames(header) <- ids
  result <- list(
    format = "aquaphotomics-workbench-r-transfer", schema_version = 1L,
    created_at = format(Sys.time(), tz = "UTC", usetz = TRUE),
    source_csv = input, preprocessed = TRUE,
    sample_id = ids, group = groups, header = header,
    wavelengths_nm = wavelengths, spectra = spectra,
    note = paste("Ordinary R list, not an aquap2 aquap_data object.",
                 "Values have already been preprocessed; consult settings.json.",
                 "No temperature calibration or molecular assignment is implied.")
  )
  temporary <- tempfile(pattern = ".aquaphotomics-rds-", tmpdir = output_parent)
  on.exit(unlink(temporary, recursive = FALSE), add = TRUE)
  saveRDS(result, temporary, version = 3, compress = "gzip")
  if (file.exists(output)) abort("The output appeared during import; it was not overwritten.")
  if (!file.rename(temporary, output)) abort("The RDS could not be moved to the requested output path.")
  invisible(result)
}

arguments <- commandArgs(trailingOnly = TRUE)
if (length(arguments) != 2L) {
  cat("Usage: Rscript r/r_import.R <extracted-result-root> <new-output.rds>\n", file = stderr())
  quit(status = 2L)
}
tryCatch({
  result <- import_workbench(arguments[[1L]], arguments[[2L]])
  cat(sprintf("Imported %d samples x %d wavelengths into an ordinary RDS list.\n",
              nrow(result$spectra), ncol(result$spectra)))
}, error = function(error) {
  cat(paste0("Import failed: ", conditionMessage(error), "\n"), file = stderr())
  quit(status = 1L)
})

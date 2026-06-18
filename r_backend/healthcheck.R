local_lib <- Sys.getenv("AQUA_R_LIBS", file.path(getwd(), "r_libs"))
dir.create(local_lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(normalizePath(local_lib, mustWork = FALSE), .libPaths()))

aquap2_available <- suppressWarnings(requireNamespace("aquap2", quietly = TRUE))
aquap2_version <- "not-installed"
if (aquap2_available) {
  aquap2_version <- as.character(utils::packageVersion("aquap2"))
}

json_escape <- function(x) {
  x <- gsub("\\\\", "\\\\\\\\", x)
  x <- gsub('"', '\\\\"', x)
  x
}

cat(sprintf(
  '{"r_version":"%s","r_home":"%s","local_lib":"%s","aquap2_available":%s,"aquap2_version":"%s"}\n',
  json_escape(R.version.string),
  json_escape(R.home()),
  json_escape(normalizePath(local_lib, mustWork = FALSE)),
  ifelse(aquap2_available, "true", "false"),
  json_escape(aquap2_version)
))

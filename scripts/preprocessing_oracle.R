#!/usr/bin/env Rscript
# Verification only: installed, integrity-checked aquap2 public preprocessing API.
args <- commandArgs(trailingOnly=TRUE)
if (length(args) != 2L) stop("Usage: preprocessing_oracle.R input.json output.json")
if (.Platform$OS.type == "windows") invisible(Sys.setlocale("LC_CTYPE", "English_United States.utf8"))
args[1] <- normalizePath(args[1],winslash="/",mustWork=TRUE)
args[2] <- normalizePath(args[2],winslash="/",mustWork=FALSE)
script_arg <- grep("^--file=", commandArgs(FALSE), value=TRUE)[1]
project <- dirname(dirname(normalizePath(sub("^--file=", "", script_arg), winslash="/", mustWork=TRUE)))
root <- normalizePath(Sys.getenv("AQUAP2_RUNTIME_ROOT", file.path(project,"qa/aquap2-runtime-v1.4")), winslash="/", mustWork=TRUE)
lib <- normalizePath(Sys.getenv("AQUAP2_LIBRARY", file.path(root,"library")), winslash="/", mustWork=TRUE)
.libPaths(c(lib,.Library))
read_raw <- function(path) readBin(path,"raw",n=file.info(path)$size)
runtime <- NULL
fallback <- function(value, default) if(is.null(value)) default else value
run <- function(input) {
  receipt <- jsonlite::parse_json(rawToChar(read_raw(file.path(root,"installation.json"))))
  pin <- "d31c1231bf71f0e73f1a630a32934602782be488"
  if (!identical(receipt$sourceCommit,pin) || !identical(receipt$sourceArchiveSha256,"22e6582a7205a723f0f70e3e3c91db272f3eefcb4eabb29023a9229091df0130")) stop("Pinned source mismatch")
  package <- find.package("aquap2",lib.loc=lib)
  if(length(receipt$installedFiles)!=4L) stop("Missing package integrity receipt")
  for(entry in receipt$installedFiles) {
    if(!entry$path %in% c("DESCRIPTION","NAMESPACE","R/aquap2.rdb","R/aquap2.rdx") ||
       digest::digest(read_raw(file.path(package,entry$path)),algo="sha256",serialize=FALSE)!=entry$sha256) stop("Installed package integrity mismatch")
  }
  suppressPackageStartupMessages(library(aquap2,lib.loc=lib))
  version <- function(name) unname(read.dcf(file.path(find.package(name),"DESCRIPTION"))[1,"Version"])
  if(version("aquap2")!="0.4.5") stop("Wrong aquap2 version")
  runtime <<- list(engine="aquap2",installedPackage=TRUE,aquap2Version="0.4.5",sourceCommit=pin,
    sourceHarnessUsed=FALSE,packageApiExecuted=FALSE,
    apis=c("aquap2::do_detrend","aquap2::do_emsc","aquap2::do_gapDer","aquap2::do_resampleNIR"),
    rVersion=R.version.string,prospectrVersion=version("prospectr"),pracmaVersion=version("pracma"))
  home <- normalizePath(file.path(root,"home"),winslash="/",mustWork=TRUE)
  if(tolower(normalizePath(Sys.getenv("HOME"),winslash="/",mustWork=TRUE))!=tolower(home)) stop("R_USER must point to isolated home before launch")
  settings <- file.path(root,"settings");Sys.setenv(AQUAP2SH=settings)
  aquap2::updateSettings(silent=TRUE)
  jobs <- file.path(root,"jobs");dir.create(jobs,showWarnings=FALSE)
  job <- tempfile("extended-preprocessing-oracle-",tmpdir=jobs);dir.create(job)
  previous <- getwd()
  # Retain oracle job inputs/artifacts; caller archives explicit QA output.
  on.exit(setwd(previous),add=TRUE)
  setwd(job);aquap2::genFolderStr();md <- aquap2::getmd(expName="artificial-preprocessing-oracle")
  if(input$schemaVersion!=1L || !length(input$cases)) stop("Invalid input schema")
  records <- lapply(input$cases,function(case) {
    cat("Artificial oracle case:",case$name,"\n")
    w <- unlist(case$wavelengths,use.names=FALSE)
    x <- do.call(rbind,lapply(case$matrix,unlist,use.names=FALSE))
    if(!is.numeric(x) || any(!is.finite(x)) || any(!is.finite(w)) || any(diff(w)<=0) || ncol(x)!=length(w) || nrow(x)<2L) stop("Invalid artificial matrix")
    rows <- sprintf("ARTIFICIAL%05d",seq_len(nrow(x)));rownames(x)<-rows
    colnames(x)<-paste0("w",format(w,scientific=FALSE,trim=TRUE,digits=17))
    header <- data.frame(C_all=factor(rep("all",nrow(x))),C_Group=factor(rep("A",nrow(x))),
      C_ECRM=factor(rep("RM",nrow(x))),Y_SampleNr=seq_len(nrow(x)),Y_conSNr=rep(1,nrow(x)),row.names=rows)
    ds <- aquap2::ttap(list(header=header,NIR=x),md=md,dol=FALSE,ncpwl=1,stf=FALSE)
    executed <- character()
    for(step in case$steps) {
      method <- step$method
      if(identical(method,"detrend")) {
        ds <- aquap2::do_detrend(ds,src=if(is.null(step$src))NULL else unlist(step$src),
          trg=if(!"trg" %in% names(step))"src" else if(is.null(step$trg))NULL else unlist(step$trg),exportModel=FALSE)
        executed <- c(executed,"aquap2::do_detrend")
      } else if(identical(method,"emsc")) {
        vec <- do.call(rbind,lapply(step$vec_load,unlist,use.names=FALSE))
        if(nrow(vec)!=ncol(ds$NIR)) stop("Invalid EMSC loading rows")
        ds <- aquap2::do_emsc(ds,vecLoad=as.data.frame(vec),exportModel=FALSE)
        executed <- c(executed,"aquap2::do_emsc")
      } else if(identical(method,"gap_derivative")) {
        ds <- aquap2::do_gapDer(ds,m=fallback(step[["m"]],1),w=fallback(step[["w"]],1),s=fallback(step[["s"]],1),deltaW=fallback(step$delta_w,1),exportModel=FALSE)
        executed <- c(executed,"aquap2::do_gapDer")
      } else if(identical(method,"resample")) {
        ds <- aquap2::do_resampleNIR(ds,targetWls=if(is.null(step$target_wavelengths))NULL else unlist(step$target_wavelengths),
          tby=fallback(step$tby,0.5),method=fallback(step$interpolation,"cubic"))
        executed <- c(executed,"aquap2::do_resampleNIR")
      } else if(identical(method,"snv")) {
        ds <- aquap2::do_snv(ds);executed<-c(executed,"aquap2::do_snv")
      } else if(identical(method,"msc")) {
        ds <- aquap2::do_msc(ds);executed<-c(executed,"aquap2::do_msc")
      } else if(identical(method,"sgolay")) {
        ds <- aquap2::do_sgolay(ds,p=fallback(step$polyorder,2),n=fallback(step$window,21),m=fallback(step$derivative,0));executed<-c(executed,"aquap2::do_sgolay")
      } else stop("Unknown oracle method")
    }
    if(!identical(rownames(ds$NIR),rows)||any(!is.finite(ds$NIR)))stop("Oracle changed row alignment or produced non-finite values")
    list(name=case$name,matrix=unname(as.matrix(ds$NIR)),wavelengths=I(unname(aquap2::getWavelengths(ds))),
      executed=I(executed),rowAlignmentPreserved=TRUE)
  })
  runtime$packageApiExecuted <<- TRUE
  list(schemaVersion=1L,ok=TRUE,runtime=runtime,cases=records)
}
sink(stderr(),type="output")
result <- tryCatch(run(jsonlite::parse_json(rawToChar(read_raw(args[1])),simplifyVector=FALSE)),
  error=function(e)list(schemaVersion=1L,ok=FALSE,error=conditionMessage(e),runtime=runtime))
sink(type="output")
writeBin(charToRaw(paste0(enc2utf8(as.character(jsonlite::toJSON(result,auto_unbox=TRUE,digits=NA,matrix="rowmajor",null="null",na="null"))),"\n")),args[2])
quit(status=if(isTRUE(result$ok))0L else 1L)

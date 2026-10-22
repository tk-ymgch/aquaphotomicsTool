#!/usr/bin/env Rscript
# Opt-in evidence only: unmodified installed aquap2 0.4.5 public gdmm PLSR.
args <- commandArgs(trailingOnly=TRUE)
if (length(args) != 2L) stop("Usage: Rscript --vanilla plsr_oracle.R input.json output.json")
script <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value=TRUE)[1])
project <- dirname(dirname(normalizePath(script, winslash="/", mustWork=TRUE)))
root <- normalizePath(Sys.getenv("AQUAP2_RUNTIME_ROOT", file.path(project,"qa/aquap2-runtime-v1.4")), winslash="/", mustWork=TRUE)
lib <- normalizePath(Sys.getenv("AQUAP2_LIBRARY",file.path(root,"library")),winslash="/",mustWork=TRUE)
.libPaths(c(lib,.Library))
read_raw <- function(path) readBin(path,"raw",n=file.info(path)$size)
if (!requireNamespace("jsonlite",quietly=TRUE)) stop("Installed jsonlite required")
runtime <- NULL
num <- function(value) {
  out <- unlist(value,use.names=FALSE)
  if (!is.numeric(out) || any(!is.finite(out))) stop("Finite numeric arrays required")
  out
}
matrix_in <- function(value) {
  if (!is.list(value) || length(value)<1 || length(unique(vapply(value,length,integer(1))))!=1L) stop("Rectangular matrix required")
  do.call(rbind,lapply(value,num))
}
curve <- function(model) {
  e <- pls::RMSEP(model,estimate=c("train","CV","adjCV"),intercept=TRUE)$val
  r <- pls::R2(model,estimate=c("train","CV"),intercept=TRUE)$val
  lapply(seq_len(model$ncomp+1L),function(i) list(components=i-1L,
    rmseCalibration=unname(e["train",1,i]),rmseCV=unname(e["CV",1,i]),rmseAdjCV=unname(e["adjCV",1,i]),
    r2Calibration=unname(r["train",1,i]),r2CV=unname(r["CV",1,i])))
}
export_model <- function(model) {
  n <- nrow(model$fitted.values); p <- length(model$Xmeans); a <- model$ncomp
  b <- matrix(model$coefficients,nrow=p,ncol=a)
  ints <- as.numeric(model$Ymeans-as.numeric(model$Xmeans %*% b))
  list(ncomp=a,xMean=I(unname(model$Xmeans)),yMean=unname(model$Ymeans[1]),
    coefficients=unname(b),intercepts=I(ints),scores=unname(matrix(model$scores,nrow=n,ncol=a)),
    loadings=unname(matrix(model$loadings,nrow=p,ncol=a)),weights=unname(matrix(model$loading.weights,nrow=p,ncol=a)),
    projection=unname(matrix(model$projection,nrow=p,ncol=a)),yLoadings=I(as.numeric(model$Yloadings)),
    fitted=unname(matrix(model$fitted.values,nrow=n,ncol=a)),
    residuals=unname(matrix(model$residuals,nrow=n,ncol=a)),
    validation=list(method=model$validation$method,segments=unname(lapply(model$validation$segments,function(s) I(as.integer(s)-1L))),
      pred=unname(matrix(model$validation$pred,nrow=n,ncol=a)),PRESS=I(as.numeric(model$validation$PRESS)),
      PRESS0=unname(model$validation$PRESS0[1]),adj=I(as.numeric(model$validation$adj)),ncomp=model$validation$ncomp),curve=curve(model))
}
run <- function(input) {
  if (!identical(input$schemaVersion,1L) && !identical(input$schemaVersion,1)) stop("Invalid schema")
  receipt <- jsonlite::parse_json(rawToChar(read_raw(file.path(root,"installation.json"))))
  pin <- "d31c1231bf71f0e73f1a630a32934602782be488"
  if (!identical(receipt$sourceCommit,pin) || !identical(receipt$sourceArchiveSha256,"22e6582a7205a723f0f70e3e3c91db272f3eefcb4eabb29023a9229091df0130")) stop("Pinned receipt mismatch")
  package <- find.package("aquap2",lib.loc=lib)
  if (!requireNamespace("digest",quietly=TRUE) || length(receipt$installedFiles)!=4L) stop("Receipt prerequisites missing")
  for (e in receipt$installedFiles) {
    if (!e$path %in% c("DESCRIPTION","NAMESPACE","R/aquap2.rdb","R/aquap2.rdx") ||
      !identical(digest::digest(read_raw(file.path(package,e$path)),algo="sha256",serialize=FALSE),e$sha256)) stop("Installed package integrity mismatch")
  }
  version <- function(name) unname(read.dcf(file.path(find.package(name,lib.loc=lib),"DESCRIPTION"))[1,"Version"])
  if (version("aquap2")!="0.4.5" || version("pls")!="2.9-0") stop("Pinned package version mismatch")
  # Each oracle invocation receives its own home/settings/work directories.
  home <- normalizePath(Sys.getenv("R_USER"),winslash="/",mustWork=TRUE)
  if (!identical(tolower(home),tolower(normalizePath(Sys.getenv("HOME"),winslash="/",mustWork=TRUE)))) stop("R_USER home mismatch")
  settings <- file.path(home,"settings"); dir.create(settings,showWarnings=FALSE)
  file.copy(file.path(root,"settings","settings.r"),file.path(settings,"settings.r"),overwrite=TRUE)
  detRange<-if(is.null(input$pls$outlierRange))0.5 else input$pls$outlierRange
  exOut<-if(is.null(input$pls$excludeOutliers))FALSE else input$pls$excludeOutliers
  if(!is.numeric(detRange)||length(detRange)!=1L||!is.finite(detRange)||detRange<0||!is.logical(exOut)||length(exOut)!=1L)stop("Invalid outlier options")
  cat("\nstn$plsr_calcInParallel <- FALSE\nstn$plsr_nrTestIterations <- 7\nstn$allSilent <- TRUE\n",
    paste0("stn$plsr_calc_exOutDetectionRange <- ",format(detRange,scientific=TRUE,digits=17),"\n"),
    file=file.path(settings,"settings.r"),append=TRUE)
  Sys.setenv(AQUAP2SH=settings)
  writeLines(paste0("AQUAP2SH = ",settings),file.path(home,".Renviron"),useBytes=TRUE)
  suppressPackageStartupMessages(library(aquap2,lib.loc=lib))
  aquap2::updateSettings(silent=TRUE)
  pls::pls.options(parallel=NULL)
  if (!identical(pls::pls.options()$plsralg,"kernelpls")) stop("Unexpected pls default algorithm")
  runtime <<- list(engine="aquap2",installedPackage=TRUE,aquap2Version="0.4.5",plsVersion=version("pls"),
    rVersion=R.version.string,sourceCommit=pin,api="aquap2::gdmm",packageApiExecuted=FALSE,
    gdmmAttempted=FALSE,sourceHarnessUsed=FALSE,algorithm="kernelpls",center=TRUE,scale=FALSE,
    rngKind=I(RNGkind()),seed=input$seed,parallel=FALSE,preprocessing="public-gdmm-native-dpt.pre-before-CV")
  x <- matrix_in(input$matrix); y <- num(input$target); w <- num(input$wavelengths)
  n <- nrow(x); p <- ncol(x)
  ids <- enc2utf8(unlist(input$ids,use.names=FALSE)); groups <- enc2utf8(unlist(input$cvGroups,use.names=FALSE))
  if (n<4 || n>1000 || p>10000 || n*p>2000000 || length(y)!=n || length(w)!=p || length(ids)!=n || length(groups)!=n || anyDuplicated(ids) || any(diff(w)<=0)) stop("Invalid input dimensions")
  dpt <- character()
  for (s in input$steps) {
    if (identical(s$method,"snv")) dpt<-c(dpt,"snv") else
    if (identical(s$method,"msc")) dpt<-c(dpt,"msc") else
    if (identical(s$method,"sgolay")) dpt<-c(dpt,paste0("sgol@",s$polyorder,"-",s$window,"-",s$derivative)) else stop("Unsupported DPT")
  }
  rows <- sprintf("ROW%07d",seq_len(n)); gnames <- unique(groups); tokens <- sprintf("G%06d",seq_along(gnames))
  sn <- if (is.null(input$sampleIds)) seq_len(n) else match(unlist(input$sampleIds),unique(unlist(input$sampleIds)))
  cons <- ave(seq_len(n),sn,FUN=seq_along)
  header <- data.frame(C_all=factor(rep("all",n)),C_CV=factor(tokens[match(groups,gnames)],levels=tokens),
    C_ECRM=factor(rep("RM",n)),Y_SampleNr=sn,Y_conSNr=cons,Y_Target=y,row.names=rows)
  rownames(x)<-rows;colnames(x)<-paste0("w",format(w,scientific=FALSE,trim=TRUE,digits=17))
  work <- file.path(home,"work");dir.create(work,showWarnings=FALSE)
  before <- getwd();on.exit(setwd(before),add=TRUE);setwd(work)
  aquap2::genFolderStr();md<-aquap2::getmd(expName="aquap2py-plsr-oracle")
  fd<-aquap2::ttap(list(header=header,NIR=x),md=md,dol=FALSE,ncpwl=1,stf=FALSE)
  valid<-input$pls$validation
  if (identical(valid,"group")) valid<-"C_CV"
  apArgs<-list(do.pca=FALSE,do.aqg=FALSE,do.pls=TRUE,do.sim=FALSE,do.da=FALSE,do.rnf=FALSE,do.svm=FALSE,do.nnet=FALSE,
    spl.var=NULL,spl.wl=NULL,dpt.pre=if (!length(dpt)) NULL else dpt,dpt.post=NULL,
    spl.do.csAvg=FALSE,spl.do.noise=FALSE,spl.do.exOut=FALSE,
    pls.regOn="Y_Target",pls.ncomp=input$pls$ncomp,pls.valid=valid,pls.exOut=exOut)
  ap<-do.call(aquap2::getap,apArgs)
  initialCube<-NULL
  if(exOut){
    initialArgs<-apArgs;initialArgs$pls.exOut<-FALSE
    set.seed(as.integer(input$seed))
    initialCube<-aquap2::gdmm(fd,ap=do.call(aquap2::getap,initialArgs))
  }
  set.seed(as.integer(input$seed))
  runtime$gdmmAttempted<<-TRUE
  cube<-aquap2::gdmm(fd,ap=ap)
  runtime$packageApiExecuted<<-TRUE
  used<-aquap2::getcd(cube,1);mods<-aquap2::getcm(cube,1,what="plsr")
  if (length(cube)!=1L || length(mods$model)!=1L || !identical(rownames(used$NIR),rows)) stop("Unexpected cube/model/row alignment")
  for (m in c(mods$model,mods$modelPlus)) {
    if(!identical(m$method,"kernelpls") || !isTRUE(m$center) || !is.null(m$scale)) stop("Actual fitted model is not centered unscaled kernelpls")
  }
  runtime$actualModelMethod<<-mods$model[[1]]$method
  runtime$actualModelCenter<<-mods$model[[1]]$center
  runtime$actualModelScalePresent<<-!is.null(mods$model[[1]]$scale)
  runtime$nativeDptSteps<<-I(dpt)
  retained<-match(rownames(mods$usedDS[[1]]$header),rows)
  if(anyNA(retained)||anyDuplicated(retained))stop("Unexpected model row mapping")
  diagnosticCube<-if(is.null(initialCube))cube else initialCube
  diagnosticMods<-aquap2::getcm(diagnosticCube,1,what="plsr")
  publicOutlier<-aquap2::pls_outlier_getIndices(diagnosticCube,detRange=detRange)[[1]][[1]]
  runtime$outlierApi<<-"aquap2::pls_outlier_getIndices"
  runtime$excludeOutliers<<-exOut
  out<-list(schemaVersion=1L,ok=TRUE,runtime=runtime,ids=I(ids[retained]),cvGroups=I(groups[retained]),
    preprocessed=unname(as.matrix(used$NIR)[retained,,drop=FALSE]),preprocessedBeforeOutlier=unname(as.matrix(used$NIR)),
    retainedIndices=I(as.integer(retained)-1L),model=export_model(mods$model[[1]]),modelPlus=export_model(mods$modelPlus[[1]]),
    outlier=list(api="aquap2::pls_outlier_getIndices",detectionRange=detRange,keepMask=I(as.logical(publicOutlier$outInd)),
      retainedIndices=I(as.integer(which(publicOutlier$outInd))-1L),excludedIndices=I(as.integer(which(!publicOutlier$outInd))-1L),
      initialModel=export_model(diagnosticMods$model[[1]])))
  if (is.null(input$pls$ncomp) && (identical(valid,"LOO") || identical(valid,"C_CV"))) {
    # gdmm does not retain selection trials. For deterministic partitions only,
    # independently replay public pls::plsr after the successful formal call.
    nc<-min(round(length(retained)*.25),30,p);sw<-12;lev<-length(unique(y[retained]))
    if(nc>lev){nc<-lev;sw<-lev-1}
    flat<-data.frame(yvar=y[retained],allData=as.matrix(used$NIR)[retained,,drop=FALSE])
    call<-list(formula=yvar~allData,data=flat,validation="CV",segments=mods$model[[1]]$validation$segments)
    if(nc>sw)call$ncomp<-nc
    selection<-do.call(pls::plsr,call)
    out$selectionReplay<-list(source="public-pls-deterministic-replay-after-formal-gdmm",ncomp=selection$ncomp,
      rmseAdjCV=I(as.numeric(pls::RMSEP(selection,estimate="adjCV",intercept=FALSE)$val)))
  }
  if (!is.null(input$unknown)) {
    ux<-matrix_in(input$unknown$matrix)
    if(ncol(ux)!=p)stop("Unknown X must already be in processed model space")
    uy<-if(is.null(input$unknown$observed))rep(NA_real_,nrow(ux))else num(input$unknown$observed)
    ur<-sprintf("UNKNOWN%05d",seq_len(nrow(ux)));rownames(ux)<-ur;colnames(ux)<-colnames(x)
    uh<-data.frame(C_all=factor(rep("all",nrow(ux))),C_ECRM=factor(rep("RM",nrow(ux))),Y_SampleNr=seq_len(nrow(ux)),Y_conSNr=rep(1,nrow(ux)),Y_Target=uy,row.names=ur)
    ud<-aquap2::ttap(list(header=uh,NIR=ux),md=md,dol=FALSE,ncpwl=1,stf=FALSE)
    pred<-aquap2::plot_pls_indepPred(ud,cube,cnv="Y_Target",inv="Y_Target",pl=FALSE,toxls=FALSE)
    out$unknown<-list(predicted=I(as.numeric(pred[[1]][[1]]$predResult)),rmse=unname(pred[[1]][[1]]$RMSEP),r2=unname(pred[[1]][[1]]$R2pr),
      api="aquap2::plot_pls_indepPred",input="already-processed-X")
  }
  out
}
sink(stderr(),type="output")
output<-tryCatch(run(jsonlite::parse_json(rawToChar(read_raw(args[1])),simplifyVector=FALSE)),error=function(e)list(schemaVersion=1L,ok=FALSE,error=list(type=class(e)[1],message=conditionMessage(e)),runtime=runtime))
sink(type="output")
text<-enc2utf8(as.character(jsonlite::toJSON(output,auto_unbox=TRUE,digits=NA,matrix="rowmajor",null="null",na="null")))
writeBin(charToRaw(paste0(text,"\n")),args[2])
quit(status=if(isTRUE(output$ok))0L else 1L)

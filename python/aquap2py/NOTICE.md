# aquap2py 0.2.0 — attribution and scope

aquap2py is an **unofficial, partial Python compatibility implementation** of
aquap2. It is not the aquap2 R package and is not represented as an upstream
release or endorsement. The complete aquap2 API is not implemented.

## License for this implementation

The aquap2py implementation is distributed under the **GNU General Public
License, version 2 or (at your option) any later version**
(`GPL-2.0-or-later`). The unmodified GPL version 2 text is provided in `LICENSE`.
There is no warranty, to the extent permitted by the license and applicable law.

This designation applies to this implementation. It does not replace the
individual notices or licenses of upstream/reference packages and dependencies.

## aquap2 reference and original authors

- Package: aquap2 0.4.5, dated 2023-08-31.
- Upstream authors, as identified in its DESCRIPTION: **Bernhard Pollner and
  Zoltan Kovacs**. Existing upstream copyright, license and warranty notices
  remain attributable to their respective authors/rightsholders; this notice
  does not assign a copyright year absent from the source.
- Fixed reference commit: `d31c1231bf71f0e73f1a630a32934602782be488`.
- Source: <https://github.com/bpollner/aquap2/tree/d31c1231bf71f0e73f1a630a32934602782be488>.
- Declared upstream license: `GPL (>=2)` in DESCRIPTION. No separate LICENSE or
  NOTICE file was present in the inspected 0.4.5 source root.

Changes/adaptation date: **2026-10-22**. The Python implementation uses NumPy/SciPy
data structures and numerical operations in place of R/S4 objects and R package
calls. It implements a limited matrix pipeline, mean-centered PCA,
classic/classic-diff Aquagrams, observed-temperature calibration with ten
non-classic Aquagram modes, and centered/unscaled PLS1/kernelpls with scoped
CV, adjusted-CV component selection and processed-X prediction. Robust LOESS,
bootstrap/balancing, PLSR-specific outlier removal, other PLS methods/multiple
responses, full R RNG parity, metadata/analysis-procedure files,
SIMCA/classification, complete import/export and R plotting/S4 semantics remain
outside this subset. The authoritative
machine-readable scope is `coverage.json`; its global compatibility flag is
false. Workbench's existing nested PLS is a separate method, not this port of
aquap2 PLSR.

Behavior/reference sources consulted for the implemented subset include:

- `R/gen_coreDataManip.r`: do_snv, do_msc, do_sgolay, do_dptSeq.
- `R/cube_generateDatasets.r`: ordered dpt module dispatch and model orchestration.
- `R/prep_transformToAp2.r`: the ttap data-model boundary (simplified in Python).
- `R/cube_makeModels.r` and `R/crw_cp.R`: mean-centered PCA and returned model fields.
- `R/calc_aqg.r`: classic/classic-diff and calibrated sfc/AUC/tn/dce formulas,
  calibration-temperature averaging, endpoint min/max, band-area ratios,
  group averaging and subtraction. The unobserved-temperature LOESS branch is
  inspected but not implemented or replaced by a different smoother.
- `inst/pData/aqugrStngs`: fixed first-overtone 12/15 coordinate ranges and labels.
- `R/calc_plsr.r`: kernelpls/CV orchestration, adjusted-CV component selection,
  additional-component model and processed-X independent prediction behavior.
- `inst/settings.r` and `inst/templates/anProc.r`: calibration SG17,
  measurement AQ SG21, mode, temperature and component-selection defaults.
- `R/gen_general.r`: getcm result extraction behavior.

These are references for numerical behavior and adaptation; they do not imply
that all of those files, APIs or options were translated or verified. The
implementation is based on mathematical operations rather than a verbatim copy
of R source strings. Any future copied or translated source must retain its own
notices and be recorded here with changed files and dates.

## Numerical dependencies and oracle references

The 2026-10-22 R oracle used the following installed reference packages:

| Reference package | Version | Declared license | Consulted behavior |
| --- | --- | --- | --- |
| aquap2 | 0.4.5 | GPL (>=2) | API, pipeline, SNV, PCA, calibrated Aquagram and PLSR semantics |
| signal | 1.8-1 | GPL-2 | sgolay/sgolayfilt coefficients, endpoints, derivative, ts=1 |
| pls | 2.9-0 | GPL-2 | msc, kernelpls equations, predictions, CV/adjCV errors |
| MASS | 7.3-65 | GPL-2 \| GPL-3 | ginv SVD cutoff behavior used by the SG reference |
| geometry | 0.5.2 | GPL (>=3) | Oracle polyarea mathematical polygon-area behavior |
| base/stats in R | 4.6.1 | Individual R source notices | Foreign-center scale/RMS and inspected, unimplemented LOESS |

`GPL-2` on signal/pls is recorded as written; it is not silently relabeled
`GPL-2.0-or-later` or GPLv3-compatible. Installed oracle dependencies retain their
individual licenses. NumPy and SciPy also retain their own licenses. This package
does not vendor the R package or those R dependency implementations.

The new polygon-area code independently expresses the mathematical unsigned
shoelace formula with NumPy. It does not copy geometry source strings, vendor
geometry, or call it at runtime. Geometry's GPL (>=3) declaration is recorded for
the oracle reference; it is not relabeled as GPL-2 or an unconditional licensing
compatibility finding. SFC expresses the foreign-center scaling formula in
NumPy. No stats LOESS implementation is copied into this release.

The PLS implementation independently expresses kernel PLS1 linear algebra,
centering, PRESS/adjusted-CV curves and coefficients with NumPy. Workbench's
existing nested-CV PLS remains a separate algorithm: this port preprocesses all
X before native CV and does not claim outer nested-CV performance equivalence.
R random-CV comparisons are conditional on concrete replayed R segments;
NumPy random sampling does not reproduce R's seed stream.

Versioned numerical evidence is recorded in coverage.json. The 0.1.0 oracle
source hashes identify that historical snapshot. They are not presented as
hashes of the complete 0.2.0 package. Current temperature/PLSR reports bind their
own source and artificial fixtures; ordinary user runs do not execute R.

The separately inspected aquap2 **0.5.1** commit
`57ee096fbecf28a321eed5884784e01b0bca036b` declares `GPL (>=3)` and is a future
comparison target only. Its implementation code is not incorporated into this
0.4.5-based port. A licensing designation here is not a legal guarantee about
every possible combination, derivative work or redistribution.

## Distribution records

When distributing modified/copied covered source, retain applicable original
notices, mark changes and dates, provide the applicable license text, and meet
the source-availability terms of the license. These are source-license review
items, not a claim that an arbitrary distribution has been legally audited.
See <https://www.r-project.org/Licenses/GPL-2> and the exact upstream DESCRIPTION.

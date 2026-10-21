# aquap2py 0.1.0 — attribution and scope

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
calls. It implements a limited matrix pipeline, mean-centered PCA, and
classic/classic-diff Aquagrams. Metadata/analysis-procedure files, temperature
calibration and AUC modes, PLSR, SIMCA/classification, complete import/export and
R plotting/S4 semantics remain outside the initial subset. The authoritative
machine-readable scope is `coverage.json`; its global compatibility flag is
false. Workbench's existing nested PLS is a separate method, not this port of
aquap2 PLSR.

Behavior/reference sources consulted for the implemented subset include:

- `R/gen_coreDataManip.r`: do_snv, do_msc, do_sgolay, do_dptSeq.
- `R/cube_generateDatasets.r`: ordered dpt module dispatch and model orchestration.
- `R/prep_transformToAp2.r`: the ttap data-model boundary (simplified in Python).
- `R/cube_makeModels.r` and `R/crw_cp.R`: mean-centered PCA and returned model fields.
- `R/calc_aqg.r`: classic/classic-diff normalization, group averaging and subtraction.
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
| aquap2 | 0.4.5 | GPL (>=2) | API, pipeline, SNV, PCA and Aquagram semantics |
| signal | 1.8-1 | GPL-2 | sgolay/sgolayfilt coefficients, endpoints, derivative, ts=1 |
| pls | 2.9-0 | GPL-2 | msc reference and normal equations |
| MASS | 7.3-65 | GPL-2 \| GPL-3 | ginv SVD cutoff behavior used by the SG reference |

`GPL-2` on signal/pls is recorded as written; it is not silently relabeled
`GPL-2.0-or-later` or GPLv3-compatible. Installed oracle dependencies retain their
individual licenses. NumPy and SciPy also retain their own licenses. This package
does not vendor the R package or those R dependency implementations.

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

# oncocs — cohort-agnostic survival-analysis pipeline on public TCGA data

Reproducible survival analysis of TCGA cohorts from cBioPortal DataHub: harmonized
patient-level data, frozen stratified splits, deterministic Cox PH and Random Survival
Forest models, survival-specific metrics, and assumption checks that produce explicit
abstentions rather than silently wrong numbers. Every run writes a self-verifying
evidence record.

## Quick start

```bash
pip install -e .[dev]
python -m oncocs download --cohort luad
python -m oncocs split --cohort luad --seed 20240601
python -m oncocs run --cohort luad --seed 20240601
python -m oncocs verify results/luad/<run_id>/results.json
```

Cohorts are config-driven (`cohorts/<id>.yaml`); adding a cohort is a yaml file, not code.

## LUAD results

TCGA LUAD PanCancer Atlas 2018, seed 20240601, 501 patients after harmonization
(350 train / 151 test; 126 / 55 events). All five checks passed; no abstentions.
Every kept sample had mutation sequencing data (0 unsequenced).

| Model / features | Harrell C | Uno C | AUC 12m | AUC 24m | AUC 36m | IBS 6–36m |
|---|---|---|---|---|---|---|
| Cox / clinical | 0.647 | 0.640 | 0.649 | 0.691 | 0.694 | 0.153 |
| RSF / clinical | 0.639 | 0.639 | 0.604 | 0.675 | 0.695 | 0.153 |
| Cox / clinical + expression | 0.643 | 0.632 | 0.711 | 0.666 | 0.628 | 0.157 |
| RSF / clinical + expression | 0.632 | 0.615 | 0.671 | 0.672 | 0.609 | 0.153 |

Top clinical Cox hazard ratios (reference: stage I, sex Female):

| Covariate | HR | 95% CI | p |
|---|---|---|---|
| stage IV | 3.27 | 1.66–6.44 | 0.0006 |
| stage III | 2.62 | 1.75–3.93 | <0.0001 |
| mut STK11 | 1.64 | 1.06–2.53 | 0.027 |
| stage II | 1.54 | 1.06–2.24 | 0.025 |

Observations:

- Adding the top-50 variance expression genes did not improve over clinical features:
  Cox C 0.643 vs 0.647; RSF C 0.632 vs 0.639.
- The `excluded_genes` list and `excluded_gene_patterns` (`^CYorf`, `^TTTY`) in
  `cohorts/luad.yaml` exist because sex-linked genes (XIST, RPS4Y1, DDX3Y, CYorf15A/B,
  etc.) dominated the variance ranking while sex is already a covariate.

## All cohorts (seed 20240601)

| Cohort | n | Events train/test | Checks | Best Harrell C (test) |
|---|---|---|---|---|
| LUAD | 501 | 126 / 55 | all 5 passed | 0.647 — cox/clinical |
| GBM | 580 | 335 / 143 | 2 passed, all 4 models abstained | — |
| BRCA | 1071 | 106 / 45 | all 5 passed | 0.708 — cox/clinical |

- GBM has no AJCC stage in this study (`stage: null` in `cohorts/gbm.yaml`;
  recorded as `omitted_covariates`), and 49% of patients lack age/sex plus 33%
  lack mutation sequencing in the source files. Every covariate exceeded the 20%
  missingness filter, so the run records a `covariates` check failure and all
  four models abstain — a legitimate outcome, not an error.
- BRCA adds `STAGE IIIC` and `STAGE X` source values. `STAGE X` ("stage cannot be
  assessed") is left unmapped and counted as missing (19 patients, 1.8%).

## Generality: cost of adding a cohort

GBM and BRCA were added as yaml-only cohorts (`cohorts/gbm.yaml`,
`cohorts/brca.yaml`) — no cohort-specific Python. The only `oncocs/` changes
between the phase-3 start commit and the end (78 lines across 3 files) were
generic fixes any cohort could trigger: Git LFS pointer detection in the
per-file download fallback, replay comparison for rejected/abstained reports,
and a clean abstention path when no covariates survive the missingness filter.

## Agent reports

`python -m oncocs agent run --cohort <id> --results <results.json> --backend
ollama --model gemma3:4b` runs a LangGraph pipeline (cohort summary → analysis
plan → report draft → deterministic claim verifier, up to 3 attempts) and writes
`results/<id>/<run_id>/agent/<agent_run_id>/{agent_run.json,report.md}`.
`agent replay <agent_run.json>` replays the recorded transcript and asserts the
report and verification are identical; `approve`/`reject` are explicit human
gates that rewrite the report banner.

The verifier checks every number in the draft against the recorded results, and
numbers appearing after a model-key mention are scoped to that model's subtree —
a number that only matches a different model is reported as `misattributed` and
fails verification.

### Human-rejected run

`results/luad/3097990b11d8/agent/7b433c558b79/` is preserved as the motivating
example: gemma3:4b produced a report whose `rsf/clinical_expression` block
listed `cox/clinical_expression`'s metrics and omitted `rsf/clinical` entirely.
Every number was real, so the original numeric verifier passed it; a human
reviewer rejected it via `oncocs reject`. The scoped verifier now segments the
draft by model-key mentions and fails that exact pattern (covered by tests).

## Limitations

- Research/education only. Not validated for clinical, diagnostic, prognostic, or
  treatment decisions.
- Public retrospective data (TCGA); results reflect the dataset, not any clinical claim.
- Checks can abstain a model's metrics (e.g. proportional-hazards violations) —
  abstention is a result, not an error.

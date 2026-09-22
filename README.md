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
| Cox / clinical + expression | 0.643 | 0.625 | 0.699 | 0.667 | 0.624 | 0.157 |
| RSF / clinical + expression | 0.651 | 0.628 | 0.715 | 0.695 | 0.645 | 0.152 |

Top clinical Cox hazard ratios (reference: stage I, sex Female):

| Covariate | HR | 95% CI | p |
|---|---|---|---|
| stage IV | 3.27 | 1.66–6.44 | 0.0006 |
| stage III | 2.62 | 1.75–3.93 | <0.0001 |
| mut STK11 | 1.64 | 1.06–2.53 | 0.027 |
| stage II | 1.54 | 1.06–2.24 | 0.025 |

Observations:

- Adding the top-50 variance expression genes did not improve over clinical features:
  Cox C 0.643 vs 0.647; RSF C 0.651 vs 0.639.
- The `excluded_genes` list in `cohorts/luad.yaml` exists because sex-linked genes
  (XIST, RPS4Y1, DDX3Y, etc.) dominated the variance ranking while sex is already a
  covariate.

## Limitations

- Research/education only. Not validated for clinical, diagnostic, prognostic, or
  treatment decisions.
- Public retrospective data (TCGA); results reflect the dataset, not any clinical claim.
- Checks can abstain a model's metrics (e.g. proportional-hazards violations) —
  abstention is a result, not an error.

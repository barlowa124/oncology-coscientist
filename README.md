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

## Limitations

- Research/education only. Not validated for clinical, diagnostic, prognostic, or
  treatment decisions.
- Public retrospective data (TCGA); results reflect the dataset, not any clinical claim.
- Checks can abstain a model's metrics (e.g. proportional-hazards violations) —
  abstention is a result, not an error.

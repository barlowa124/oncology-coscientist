"""oncocs command line: download / split / run / verify."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sksurv.util import Surv

from oncocs import checks, evidence
from oncocs.config import DEFAULT_ROOT, load_cohort
from oncocs.data.download import download_cohort, load_manifest
from oncocs.data.harmonize import harmonize
from oncocs.data.load import (load_cases_sequenced, load_clinical_patient,
                              load_clinical_sample, load_expression,
                              load_mutations)
from oncocs.models.cox import cox_summary, cox_survival, fit_cox
from oncocs.models.metrics import evaluate
from oncocs.models.rsf import fit_rsf, rsf_risk, rsf_survival
from oncocs.prep import prepare_features
from oncocs.splits import load_split, make_split


def _harmonized(cfg, root):
    patients, expr, report = harmonize(
        cfg,
        load_clinical_patient(cfg, root),
        load_clinical_sample(cfg, root),
        load_expression(cfg, root),
        load_mutations(cfg, root),
        load_cases_sequenced(cfg, root),
    )
    return patients, expr, report


def cmd_download(args):
    cfg = load_cohort(args.cohort, args.data_dir)
    manifest = download_cohort(cfg, args.data_dir)
    print(json.dumps({"cohort": cfg.cohort, "manifest_sha256": manifest["manifest_sha256"]}, indent=2))


def cmd_split(args):
    cfg = load_cohort(args.cohort, args.data_dir)
    patients, _, report = _harmonized(cfg, args.data_dir)
    manifest = load_manifest(cfg, args.data_dir)
    split = make_split(patients, cfg, seed=args.seed, test_fraction=args.test_fraction,
                       data_manifest_sha256=manifest["manifest_sha256"],
                       root=args.data_dir, force=args.force)
    print(json.dumps({k: split[k] for k in ("cohort", "seed", "n_train", "n_test", "split_sha256")}, indent=2))


def _run_pipeline(cfg, root, seed):
    """Full pipeline; returns (record_dict, patients)."""
    patients, expr, report = _harmonized(cfg, root)
    manifest = load_manifest(cfg, root)
    split = load_split(cfg, root)
    train_ids, test_ids = split["train_ids"], split["test_ids"]

    record = evidence.build_record(cfg.cohort, seed, Path(root),
                                   manifest["manifest_sha256"], split["split_sha256"],
                                   cfg.config_sha256)
    record["missingness"] = report["missingness"]
    record["dropped"] = report["dropped"]
    record["n_patients"] = report.get("n_patients_final")
    record["n_patients_with_expression"] = report.get("n_patients_with_expression")
    record["n_unsequenced_patients"] = report.get("n_unsequenced_patients")

    run_checks = [
        checks.check_split_integrity(split, patients.index),
        checks.check_min_events(patients.loc[train_ids, "event"], patients.loc[test_ids, "event"]),
    ]

    kinds = report["covariates_used"]
    max_t = float(patients.loc[test_ids, "os_months"].max())
    grid = np.linspace(0, max_t, 200)
    y_train = Surv.from_arrays(patients.loc[train_ids, "event"].astype(bool),
                               patients.loc[train_ids, "os_months"])
    y_test = Surv.from_arrays(patients.loc[test_ids, "event"].astype(bool),
                              patients.loc[test_ids, "os_months"])

    models = {}
    cox_clinical = None
    for fs in ("clinical", "clinical_expression"):
        include_expr = fs == "clinical_expression"
        X_tr, X_te, meta = prepare_features(
            patients, expr if include_expr else None, train_ids, test_ids,
            kinds, cfg.n_expression_genes if include_expr else 0, include_expr,
            cfg.excluded_genes)

        train_df = X_tr.assign(os_months=patients.loc[train_ids, "os_months"],
                               event=patients.loc[train_ids, "event"])

        # Cox
        try:
            cph = fit_cox(train_df)
            cox_metrics = evaluate(y_train, y_test,
                                   np.asarray(cph.predict_partial_hazard(X_te)).ravel(),
                                   cox_survival(cph, X_te, grid), grid)
            cox_out = {"metrics": cox_metrics}
            if fs == "clinical":
                cox_clinical = cph
                cox_clinical_df = train_df
                cox_out["hazard_ratios"] = cox_summary(cph)
                cox_out["reference_levels"] = meta["reference_levels"]
        except Exception as exc:
            cox_out = {"metrics": {"abstained": True, "reason": f"fit/eval failed: {exc}"}}
        models[f"cox/{fs}"] = cox_out

        # RSF
        try:
            rsf = fit_rsf(train_df, seed)
            rsf_metrics = evaluate(y_train, y_test, rsf_risk(rsf, X_te),
                                   rsf_survival(rsf, X_te, grid), grid)
            models[f"rsf/{fs}"] = {"metrics": rsf_metrics}
            if include_expr:
                models[f"rsf/{fs}"]["gene_cols"] = meta["gene_cols"]
                cox_out["gene_cols"] = meta["gene_cols"]
        except Exception as exc:
            models[f"rsf/{fs}"] = {"metrics": {"abstained": True, "reason": f"fit/eval failed: {exc}"}}
            if include_expr:
                models[f"rsf/{fs}"]["gene_cols"] = meta["gene_cols"]
                cox_out["gene_cols"] = meta["gene_cols"]

        if fs == "clinical_expression":
            run_checks.append(checks.check_leakage(
                patients.loc[train_ids], expr.loc[train_ids], kinds,
                cfg.n_expression_genes, meta["gene_cols"], meta["impute"], meta["scale"],
                cfg.excluded_genes))

    if cox_clinical is not None:
        run_checks.append(checks.check_proportional_hazards(cox_clinical, cox_clinical_df))
        run_checks.append(checks.check_convergence(cox_clinical))
    else:
        run_checks.append({"name": "proportional_hazards", "passed": False,
                           "detail": {"reason": "clinical Cox model did not fit"},
                           "affects": "cox_clinical"})
        run_checks.append({"name": "convergence", "passed": False,
                           "detail": {"converged": False}, "affects": "cox"})
    record["checks"] = run_checks

    # Apply abstentions
    failed = [c for c in run_checks if not c["passed"]]
    for name, out in models.items():
        reasons = []
        for c in failed:
            if c["affects"] == "all":
                reasons.append(f"{c['name']} failed")
            elif c["affects"] == "cox_clinical" and name == "cox/clinical":
                reasons.append(f"{c['name']} failed")
            elif c["affects"] == "cox" and name.startswith("cox/"):
                reasons.append(f"{c['name']} failed")
        if reasons:
            out["metrics"] = {"abstained": True, "reason": "; ".join(reasons)}
            out.pop("hazard_ratios", None)
    record["models"] = models
    return record


def cmd_run(args):
    cfg = load_cohort(args.cohort, args.data_dir)
    record = _run_pipeline(cfg, args.data_dir, args.seed)
    if record.get("git_dirty"):
        print("WARNING: git working tree is dirty; results are not bound to a clean commit.",
              file=sys.stderr)
    path = evidence.write_results(record, Path(args.data_dir))
    print(f"Results written to {path}")
    for c in record["checks"]:
        print(f"  check {c['name']}: {'PASS' if c['passed'] else 'FAIL'}")
    for name, out in record["models"].items():
        m = out["metrics"]
        tag = "ABSTAINED" if m.get("abstained") else f"C={m.get('harrell_c'):.3f}"
        print(f"  {name}: {tag}")


def cmd_verify(args):
    root = Path(args.data_dir)
    record = json.loads(Path(args.results).read_text())
    cfg = load_cohort(record["cohort"], root)

    # recompute data manifest
    manifest_path = root / "data" / record["cohort"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    from oncocs.data.download import _sha256_file
    ok = True
    for name, sha in manifest["members"].items():
        actual = _sha256_file(root / "data" / record["cohort"] / "raw" / name)
        if actual != sha:
            print(f"FAIL: member {name} sha mismatch")
            ok = False
    canon = json.dumps({k: v for k, v in manifest.items() if k != "manifest_sha256"},
                       sort_keys=True).encode()
    import hashlib
    if hashlib.sha256(canon).hexdigest() != manifest["manifest_sha256"]:
        print("FAIL: manifest hash mismatch")
        ok = False
    if manifest["manifest_sha256"] != record["data_manifest_sha256"]:
        print("FAIL: manifest hash does not match recorded run")
        ok = False

    # recompute split hash
    split = load_split(cfg, root)
    from oncocs.splits import split_sha256
    if split_sha256(split["train_ids"], split["test_ids"]) != record["split_sha256"]:
        print("FAIL: split hash mismatch")
        ok = False

    # rerun with recorded seed and compare
    rerun = _run_pipeline(cfg, root, record["seed"])
    if evidence.strip_volatile(rerun) == evidence.strip_volatile(record):
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    print("FAIL: rerun results differ from recorded results")
    return 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="oncocs")
    p.add_argument("--data-dir", default=str(DEFAULT_ROOT),
                   help="project root containing cohorts/, data/, splits/, results/")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("download")
    d.add_argument("--cohort", required=True)
    d.set_defaults(fn=cmd_download)

    s = sub.add_parser("split")
    s.add_argument("--cohort", required=True)
    s.add_argument("--seed", type=int, required=True)
    s.add_argument("--test-fraction", type=float, default=0.3)
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_split)

    r = sub.add_parser("run")
    r.add_argument("--cohort", required=True)
    r.add_argument("--seed", type=int, required=True)
    r.set_defaults(fn=cmd_run)

    v = sub.add_parser("verify")
    v.add_argument("results")
    v.set_defaults(fn=cmd_verify)

    args = p.parse_args(argv)
    args.data_dir = Path(args.data_dir)
    rc = args.fn(args)
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())

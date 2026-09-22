"""Load raw cohort files into dataframes."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from oncocs.config import CohortConfig, DEFAULT_ROOT


def _read_clinical(path: Path) -> pd.DataFrame:
    """cBioPortal clinical files have 4 '#' comment lines before the header."""
    return pd.read_csv(path, sep="\t", comment="#", dtype=str, low_memory=False)


def load_clinical_patient(cfg: CohortConfig, root: Path | str = DEFAULT_ROOT) -> pd.DataFrame:
    return _read_clinical(Path(root) / "data" / cfg.cohort / "raw" / cfg.files["clinical_patient"])


def load_clinical_sample(cfg: CohortConfig, root: Path | str = DEFAULT_ROOT) -> pd.DataFrame:
    return _read_clinical(Path(root) / "data" / cfg.cohort / "raw" / cfg.files["clinical_sample"])


def load_expression(cfg: CohortConfig, root: Path | str = DEFAULT_ROOT) -> pd.DataFrame:
    """Raw RSEM expression; genes x samples. Returns samples x genes (log2(x+1))."""
    raw_dir = Path(root) / "data" / cfg.cohort / "raw"
    primary = raw_dir / cfg.files["expression"]
    path = primary if primary.exists() else raw_dir / cfg.files["expression_fallback"]
    df = pd.read_csv(path, sep="\t", low_memory=False)
    idcol = "Hugo_Symbol" if "Hugo_Symbol" in df.columns else df.columns[0]
    df = df.dropna(subset=[idcol]).drop_duplicates(subset=[idcol]).set_index(idcol)
    dropcols = [c for c in ("Entrez_Gene_Id",) if c in df.columns]
    df = df.drop(columns=dropcols)
    expr = df.apply(pd.to_numeric, errors="coerce").T
    return np.log2(expr + 1)


def load_mutations(cfg: CohortConfig, root: Path | str = DEFAULT_ROOT) -> pd.DataFrame:
    path = Path(root) / "data" / cfg.cohort / "raw" / cfg.files["mutations"]
    return pd.read_csv(path, sep="\t", comment="#", dtype=str, low_memory=False)

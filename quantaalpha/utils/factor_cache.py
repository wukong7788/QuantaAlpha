from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def md5_key(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _env_truthy(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _get_cache_format(config: Optional[Dict[str, Any]] = None) -> str:
    """
    Returns: "parquet" or "pkl"
    Default: parquet
    """
    if config is not None:
        v = str(config.get("cache_format", "")).strip().lower()
        if v in {"parquet", "pkl"}:
            return v
    v = str(os.getenv("QUANTA_FACTOR_CACHE_FORMAT", "parquet")).strip().lower()
    return v if v in {"parquet", "pkl"} else "parquet"


def _get_parquet_compression(config: Optional[Dict[str, Any]] = None) -> str:
    if config is not None:
        v = str(config.get("cache_compression", "")).strip().lower()
        if v:
            return v
    return str(os.getenv("QUANTA_FACTOR_CACHE_COMPRESSION", "zstd")).strip().lower() or "zstd"


def _dual_write_pkl(config: Optional[Dict[str, Any]] = None) -> bool:
    if config is not None and "cache_dual_write_pkl" in config:
        return bool(config.get("cache_dual_write_pkl"))
    return _env_truthy("QUANTA_FACTOR_CACHE_DUAL_WRITE_PKL", "false")


def cache_paths(cache_dir: Union[str, Path], cache_key: str) -> Tuple[Path, Path]:
    cache_dir = Path(cache_dir)
    return cache_dir / f"{cache_key}.parquet", cache_dir / f"{cache_key}.pkl"


def _normalize_to_series(result: Any, source: str = "") -> Optional[pd.Series]:
    try:
        if result is None:
            return None

        if isinstance(result, pd.DataFrame):
            if len(result.columns) == 1:
                result = result.iloc[:, 0]
            elif "factor" in result.columns:
                result = result["factor"]
            else:
                result = result.iloc[:, 0]

        if not isinstance(result, pd.Series):
            return None

        if isinstance(result.index, pd.MultiIndex):
            expected = ["datetime", "instrument"]
            names = list(result.index.names)
            if names != expected and set(names) == set(expected):
                result = result.swaplevel().sort_index()

        return result
    except Exception as e:
        logger.debug(f"Normalize cache result failed [{source}]: {e}")
        return None


def _series_to_parquet_df(series: pd.Series) -> pd.DataFrame:
    s = series
    if isinstance(s.index, pd.MultiIndex) and s.index.nlevels >= 2:
        idx_names = list(s.index.names)
        if len(idx_names) < 2:
            idx_names = ["datetime", "instrument"]
            s.index = s.index.set_names(idx_names[: s.index.nlevels])
        else:
            if idx_names[0] is None:
                idx_names[0] = "datetime"
            if idx_names[1] is None:
                idx_names[1] = "instrument"
            s.index = s.index.set_names(idx_names)
    df = s.to_frame("factor").reset_index()
    return df


def _parquet_df_to_series(df: pd.DataFrame, source: str = "") -> Optional[pd.Series]:
    try:
        if df is None or len(df) == 0:
            return None

        factor_col = "factor"
        if factor_col not in df.columns:
            non_index_cols = [c for c in df.columns if c not in {"datetime", "instrument"}]
            if len(non_index_cols) == 1:
                factor_col = non_index_cols[0]
            else:
                factor_col = df.columns[-1]

        if {"datetime", "instrument"}.issubset(set(df.columns)):
            s = df.set_index(["datetime", "instrument"])[factor_col]
            return _normalize_to_series(s, source=source)

        # Fallback: first two columns are treated as index, last as value.
        if len(df.columns) >= 3:
            idx_cols = list(df.columns[:2])
            s = df.set_index(idx_cols)[factor_col]
            s.index = s.index.set_names(["datetime", "instrument"])
            return _normalize_to_series(s, source=source)

        return None
    except Exception as e:
        logger.debug(f"Parquet->Series failed [{source}]: {e}")
        return None


def read_factor_cache(
    cache_dir: Union[str, Path],
    cache_key: str,
    *,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[pd.Series]:
    """
    Parquet-first by default, with pickle fallback for compatibility.
    """
    parquet_path, pkl_path = cache_paths(cache_dir, cache_key)
    fmt = _get_cache_format(config)

    candidates = [(parquet_path, "parquet"), (pkl_path, "pkl")] if fmt == "parquet" else [(pkl_path, "pkl"), (parquet_path, "parquet")]

    for path, kind in candidates:
        if not path.exists():
            continue
        try:
            if kind == "parquet":
                df = pd.read_parquet(path, engine="pyarrow")
                s = _parquet_df_to_series(df, source=str(path))
            else:
                s = _normalize_to_series(pd.read_pickle(path), source=str(path))
            if s is not None:
                return s.astype(np.float64, copy=False)
        except Exception as e:
            logger.debug(f"Cache read failed [{kind} {path.name}]: {e}")
            continue

    return None


def write_factor_cache(
    cache_dir: Union[str, Path],
    cache_key: str,
    series: pd.Series,
    *,
    config: Optional[Dict[str, Any]] = None,
    strict_parquet: bool = False,
) -> bool:
    """
    Default writes Parquet+ZSTD; optional dual-write pickle for rollback.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    s = _normalize_to_series(series, source="write_factor_cache")
    if s is None:
        return False

    fmt = _get_cache_format(config)
    compression = _get_parquet_compression(config)
    parquet_path, pkl_path = cache_paths(cache_dir, cache_key)

    if fmt == "pkl":
        try:
            s.to_pickle(pkl_path)
            return True
        except Exception as e:
            logger.warning(f"Save cache failed [pkl {pkl_path.name}]: {e}")
            return False

    # parquet
    try:
        df = _series_to_parquet_df(s)
        df.to_parquet(parquet_path, index=False, engine="pyarrow", compression=compression)
    except Exception as e:
        logger.warning(f"Save cache failed [parquet {parquet_path.name}]: {e}")
        if strict_parquet:
            return False
        # Fallback to pickle to avoid losing caching entirely.
        try:
            s.to_pickle(pkl_path)
            return True
        except Exception as e2:
            logger.warning(f"Save cache fallback failed [pkl {pkl_path.name}]: {e2}")
            return False

    if _dual_write_pkl(config):
        try:
            s.to_pickle(pkl_path)
        except Exception as e:
            logger.debug(f"Dual-write pkl failed [{pkl_path.name}]: {e}")

    return True

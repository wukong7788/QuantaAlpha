#!/usr/bin/env python3
"""
Custom factor calculator using AlphaAgent expression parser.
Supports the same expression syntax as factor mining.

Features:
1. Parse factor expressions (expr_parser)
2. Compute factor values (function_lib)
3. Output Qlib DataLoader-compatible format
4. Load precomputed factors from cache
"""

import hashlib
import json
import logging
import os
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

# Add project root (from quantaalpha/backtest/ up two levels)
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

warnings.filterwarnings('ignore', category=FutureWarning, module='pandas')
warnings.filterwarnings('ignore', category=UserWarning, module='quantaalpha')

# Use thread backend for joblib to avoid subprocess importing LLM modules
os.environ.setdefault('JOBLIB_START_METHOD', 'loky')

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(os.environ.get("FACTOR_CACHE_DIR", "data/results/factor_cache"))


class CustomFactorCalculator:
    """
    Custom factor calculator using AlphaAgent expression parser and function lib.
    Loads precomputed factors from cache; can auto-extract cache from main program logs.
    """
    
    def __init__(self, data_df: Optional[pd.DataFrame] = None, cache_dir: Optional[Path] = None, 
                 auto_extract_cache: bool = True, config: Optional[Dict] = None):
        """
        Args:
            data_df: Stock data DataFrame (optional, lazy-loaded).
            cache_dir: Cache directory path (optional).
            auto_extract_cache: Whether to auto-extract cache from main program logs (default True).
            config: Config dict for lazy loading data (optional).
        """
        self._raw_data_df = data_df
        self._data_prepared = False
        self._config = config
        self._llm_cache_config = (config or {}).get("llm", {}) if isinstance(config, dict) else {}
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.auto_extract_cache = auto_extract_cache
        self._cache_extracted = False
        
        if data_df is not None and len(data_df) > 0:
            self._prepare_data()
    
    @property
    def data_df(self) -> pd.DataFrame:
        """Lazy-load stock data."""
        if not self._data_prepared:
            if self._raw_data_df is None or len(self._raw_data_df) == 0:
                if self._config is not None:
                    print("  Loading stock data (needed for expression-based factor computation)...")
                    self._raw_data_df = get_qlib_stock_data(self._config)
                else:
                    raise ValueError("No stock data provided and no config for loading")
            self._prepare_data()
        return self._raw_data_df
        
    def _prepare_data(self):
        """Prepare data and add common derived columns."""
        if self._data_prepared:
            return
        
        df = self._raw_data_df.copy()
        
        if '$return' not in df.columns:
            df['$return'] = df.groupby('instrument')['$close'].transform(
                lambda x: x / x.shift(1) - 1
            )
        
        if df.index.duplicated().any():
            dup_count = df.index.duplicated().sum()
            logger.warning(f"Data has {dup_count} duplicate index entries, deduplicated")
            df = df[~df.index.duplicated(keep='last')]
        
        self._raw_data_df = df
        self._data_prepared = True
        logger.debug(f"Data prepared: {len(df)} rows, cols: {list(df.columns)}")
    
    def _get_cache_key(self, expr: str) -> str:
        """Cache key from expression MD5 hash."""
        return hashlib.md5(expr.encode()).hexdigest()
    
    def _load_from_cache(self, expr: str) -> Optional[pd.Series]:
        """Load factor values from cache."""
        from quantaalpha.utils.factor_cache import read_factor_cache

        cache_key = self._get_cache_key(expr)
        try:
            return read_factor_cache(self.cache_dir, cache_key, config=self._llm_cache_config)
        except Exception as e:
            logger.debug(f"Cache load failed [{cache_key}]: {e}")
            return None
    
    def _load_from_cache_location(self, cache_location: Dict) -> Optional[pd.Series]:
        """Load factor from path given in cache_location."""
        if not cache_location:
            return None
        
        result_h5_path = cache_location.get('result_h5_path', '')
        if not result_h5_path:
            return None
        
        h5_file = Path(result_h5_path)
        if not h5_file.exists():
            logger.debug(f"Cache file not found: {result_h5_path}")
            return None
        
        try:
            result = pd.read_hdf(str(h5_file))
            return self._process_cached_result(result, result_h5_path)
        except Exception as e:
            logger.debug(f"Load from cache_location failed [{result_h5_path}]: {e}")
            return None
    
    def _process_cached_result(self, result: Any, source: str) -> Optional[pd.Series]:
        """Normalize cached result format (does not touch self.data_df to avoid lazy load)."""
        try:
            if isinstance(result, pd.DataFrame):
                if len(result.columns) == 1:
                    result = result.iloc[:, 0]
                elif 'factor' in result.columns:
                    result = result['factor']
                else:
                    result = result.iloc[:, 0]
            
            # Standard order: (datetime, instrument)
            if isinstance(result.index, pd.MultiIndex):
                cache_idx_names = list(result.index.names)
                expected_order = ['datetime', 'instrument']
                if cache_idx_names != expected_order and set(cache_idx_names) == set(expected_order):
                    result = result.swaplevel()
                    result = result.sort_index()
            
            return result
        except Exception as e:
            logger.debug(f"Process cached result failed [{source}]: {e}")
            return None
    
    def _save_to_cache(self, expr: str, result: pd.Series):
        """Save factor values to cache."""
        from quantaalpha.utils.factor_cache import write_factor_cache

        try:
            cache_key = self._get_cache_key(expr)
            write_factor_cache(self.cache_dir, cache_key, result, config=self._llm_cache_config)
        except Exception as e:
            logger.warning(f"Save to cache failed: {e}")
    
    def _auto_extract_cache_from_logs(self):
        """Auto-extract cache from main program logs; runs once on first need."""
        if self._cache_extracted:
            return
        
        self._cache_extracted = True
        
        try:
            from tools.factor_cache_extractor import extract_factors_to_cache
            
            logger.debug("Auto-extracting main program cache...")
            new_count = extract_factors_to_cache(
                output_dir=self.cache_dir,
                verbose=False
            )
            if new_count > 0:
                logger.debug(f"Extracted {new_count} factors to cache")
        except ImportError:
            logger.debug("Cache extractor not available, skip auto-extract")
        except Exception as e:
            logger.warning(f"Auto-extract cache failed: {e}")
        
    def calculate_factor(self, factor_name: str, factor_expression: str) -> Optional[pd.Series]:
        """
        Compute a single factor.
        Returns: pd.Series with MultiIndex (datetime, instrument).
        """
        try:
            import io
            import sys as _sys
            from joblib import parallel_backend
            
            from quantaalpha.factors.coder.expr_parser import (
                parse_expression, parse_symbol
            )
            import quantaalpha.factors.coder.function_lib as func_lib
            
            df = self.data_df.copy()
            
            expr = parse_symbol(factor_expression, df.columns)
            
            old_stdout = _sys.stdout
            _sys.stdout = io.StringIO()
            try:
                expr = parse_expression(expr)
            finally:
                _sys.stdout = old_stdout
            
            for col in df.columns:
                if col.startswith('$'):
                    expr = expr.replace(col[1:], f"df['{col}']")
            
            exec_globals = {
                'df': df,
                'np': np,
                'pd': pd,
            }
            
            for name in dir(func_lib):
                if not name.startswith('_'):
                    obj = getattr(func_lib, name)
                    if callable(obj):
                        exec_globals[name] = obj
            
            with parallel_backend('threading', n_jobs=1):
                result = eval(expr, exec_globals)
            
            if isinstance(result, pd.DataFrame):
                result = result.iloc[:, 0]
            
            if isinstance(result, pd.Series):
                result.name = factor_name
                # Align result index with raw data (duplicate-safe)
                if not result.index.equals(df.index):
                    try:
                        if result.index.duplicated().any():
                            result = result[~result.index.duplicated(keep='last')]
                        result = result.reindex(df.index)
                    except Exception:
                        logger.debug(f"reindex fallback for [{factor_name}]")
                        result = result[~result.index.duplicated(keep='last')]
                        clean_idx = df.index[~df.index.duplicated(keep='last')]
                        result = result.reindex(clean_idx)
                return result.astype(np.float64)
            else:
                return pd.Series(result, index=df.index, name=factor_name).astype(np.float64)
                
        except Exception as e:
            logger.warning(f"Factor computation failed [{factor_name}]: {str(e)[:200]}")
            return None
    
    def calculate_factors_from_json(self, json_path: str, 
                                   max_factors: Optional[int] = None) -> pd.DataFrame:
        """Batch compute factors from JSON file."""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        factors = data.get('factors', {})
        
        results = {}
        used_keys = set()
        success_count = 0
        fail_count = 0
        
        factor_items = list(factors.items())
        if max_factors:
            factor_items = factor_items[:max_factors]
        
        total = len(factor_items)
        logger.debug(f"Computing {total} factors...")
        
        for i, (factor_id, factor_info) in enumerate(factor_items):
            factor_name = factor_info.get('factor_name', factor_id)
            factor_expr = factor_info.get('factor_expression', '')
            
            if not factor_expr:
                fail_count += 1
                continue

            # Ensure unique column names even if factor_name repeats.
            col_key = str(factor_name or factor_id or "unknown").strip()
            if col_key in used_keys:
                col_key = f"{col_key}__{factor_id}"
            used_keys.add(col_key)
            
            if (i + 1) % 10 == 0 or i == 0:
                logger.debug(f"  Progress: {i+1}/{total}")
            
            result = self.calculate_factor(factor_name, factor_expr)
            
            if result is not None:
                results[col_key] = result
                success_count += 1
            else:
                fail_count += 1
        
        print(f"Factor computation done: success {success_count}, failed {fail_count}")
        
        if results:
            return pd.DataFrame(results)
        return pd.DataFrame()
    
    def calculate_factors_batch(self, factors: List[Dict], use_cache: bool = True,
                                skip_compute: bool = False) -> pd.DataFrame:
        """
        Batch compute factors. Priority: 1) cache_location (result.h5),
        2) MD5 cache (factor_cache dir), 3) recompute from factor_expression
        (skipped when skip_compute=True). skip_compute=True skips cache misses.
        """
        import time as _time
        
        if use_cache and self.auto_extract_cache:
            self._auto_extract_cache_from_logs()

        # IMPORTANT:
        # Cache entries are keyed only by expression MD5, so different runs (market/date range/data version)
        # may produce different indexes. We must align everything to the *current* target index; otherwise
        # we will silently drop factors or blow up memory by constructing a huge union index.
        target_index: Optional[pd.Index] = None
        if factors:
            try:
                target_index = self.data_df.index
                if isinstance(target_index, pd.MultiIndex) and target_index.duplicated().any():
                    target_index = target_index[~target_index.duplicated(keep='last')]
            except Exception as e:
                logger.debug(f"Target index unavailable, will align by cached index only: {e}")
                target_index = None

        results: Dict[str, pd.Series] = {}
        used_keys: set[str] = set()
        renamed_duplicates: List[Tuple[str, str]] = []
        success_count = 0
        fail_count = 0
        cache_hit_count = 0
        cache_location_hit_count = 0
        compute_count = 0
        failed_names: List[str] = []
        total = len(factors)
        need_compute_factors: List[Tuple[int, str, Dict]] = []

        def _validate(series: Optional[pd.Series], name: str) -> Optional[pd.Series]:
            if series is None:
                return None
            if target_index is not None:
                return self._validate_and_align_result(series, name, target_index)
            # Fallback: at least filter out empty/all-NaN results when target index is unavailable.
            return series if len(series) > 0 and not series.isna().all() else None

        def _reserve_factor_key(factor_info: Dict, factor_name: str) -> str:
            """Return a unique column key for this factor.

            Some factor libraries contain duplicate factor_name values. If we key results by
            factor_name, later factors overwrite earlier ones silently and the effective
            factor count becomes smaller than requested.
            """
            raw_name = str(factor_name or "unknown").strip() or "unknown"
            raw_id = str(factor_info.get("factor_id") or "").strip()
            key = raw_name
            if key not in used_keys:
                used_keys.add(key)
                return key
            if raw_id:
                key2 = f"{raw_name}__{raw_id}"
                if key2 not in used_keys:
                    used_keys.add(key2)
                    renamed_duplicates.append((raw_name, key2))
                    return key2
            # Fallback: keep appending a numeric suffix.
            n = 2
            while True:
                key2 = f"{raw_name}__dup{n}"
                if key2 not in used_keys:
                    used_keys.add(key2)
                    renamed_duplicates.append((raw_name, key2))
                    return key2
                n += 1
        
        # Pass 1: load from cache
        for i, factor_info in enumerate(factors):
            factor_name = factor_info.get('factor_name', 'unknown')
            factor_expr = factor_info.get('factor_expression', '')
            cache_location = factor_info.get('cache_location')
            
            if not factor_expr:
                fail_count += 1
                failed_names.append(factor_name)
                continue

            factor_key = _reserve_factor_key(factor_info, factor_name)
            
            result = None
            
            if use_cache and cache_location:
                h5_path = cache_location.get('result_h5_path', '')
                if h5_path:
                    result = self._load_from_cache_location(cache_location)
                    if result is not None:
                        validated = _validate(result, factor_name)
                        if validated is not None:
                            cache_location_hit_count += 1
                            results[factor_key] = validated
                            success_count += 1
                            print(f"  [{i+1}/{total}] ✓ H5 cache: {factor_name}")
                            continue
                        print(f"  [{i+1}/{total}] ⚠ Invalid H5 cache: {factor_name} (index mismatch)")
            
            if use_cache:
                result = self._load_from_cache(factor_expr)
                if result is not None:
                    validated = _validate(result, factor_name)
                    if validated is not None:
                        cache_hit_count += 1
                        results[factor_key] = validated
                        success_count += 1
                        print(f"  [{i+1}/{total}] ✓ MD5 cache: {factor_name}")
                        continue
                    print(f"  [{i+1}/{total}] ⚠ Invalid MD5 cache: {factor_name} (index mismatch)")
            
            need_compute_factors.append((i, factor_key, factor_info))
            print(f"  [{i+1}/{total}] ⏳ Pending: {factor_name}")
        
        # Pass 2: compute uncached factors
        if need_compute_factors:
            if skip_compute:
                skipped_count = len(need_compute_factors)
                skipped_names = [f.get('factor_name', 'unknown') for _, _, f in need_compute_factors]
                print(f"  Skipping {skipped_count} uncached factors (skip_compute=True)")
                if skipped_names:
                    print(f"  Skipped: {', '.join(skipped_names)}")
            else:
                print(f"  Computing {len(need_compute_factors)} factors from expressions...")
                
                for idx, (orig_i, factor_key, factor_info) in enumerate(need_compute_factors):
                    factor_name = factor_info.get('factor_name', 'unknown')
                    factor_expr = factor_info.get('factor_expression', '')
                    
                    print(f"  Compute [{idx+1}/{len(need_compute_factors)}]: {factor_name} ...", end='', flush=True)
                    t0 = _time.time()
                    
                    try:
                        import signal as _signal
                        
                        class _FactorTimeout(Exception):
                            pass
                        
                        def _timeout_handler(signum, frame):
                            raise _FactorTimeout()
                        
                        old_handler = None
                        try:
                            old_handler = _signal.signal(_signal.SIGALRM, _timeout_handler)
                            _signal.alarm(120)
                        except (AttributeError, ValueError):
                            pass
                        
                        result = self.calculate_factor(factor_name, factor_expr)
                        
                        try:
                            _signal.alarm(0)
                            if old_handler is not None:
                                _signal.signal(_signal.SIGALRM, old_handler)
                        except (AttributeError, ValueError):
                            pass
                        
                    except _FactorTimeout:
                        elapsed = _time.time() - t0
                        print(f" ✗ Timeout ({elapsed:.1f}s)")
                        fail_count += 1
                        failed_names.append(f"{factor_name}(timeout)")
                        try:
                            _signal.alarm(0)
                            if old_handler is not None:
                                _signal.signal(_signal.SIGALRM, old_handler)
                        except (AttributeError, ValueError):
                            pass
                        continue
                    except Exception as e:
                        elapsed = _time.time() - t0
                        print(f" ✗ Error ({elapsed:.1f}s): {str(e)[:80]}")
                        fail_count += 1
                        failed_names.append(factor_name)
                        continue
                    
                    elapsed = _time.time() - t0
                    
                    if result is not None and len(result) > 0:
                        if not result.isna().all():
                            validated = _validate(result, factor_name)
                            if validated is not None:
                                results[factor_key] = validated
                                success_count += 1
                                compute_count += 1
                                print(f" ✓ ({elapsed:.1f}s)")
                                if use_cache:
                                    self._save_to_cache(factor_expr, validated)
                            else:
                                fail_count += 1
                                failed_names.append(factor_name)
                                print(f" ✗ Invalid index ({elapsed:.1f}s)")
                        else:
                            fail_count += 1
                            failed_names.append(factor_name)
                            print(f" ✗ All NaN ({elapsed:.1f}s)")
                    else:
                        fail_count += 1
                        failed_names.append(factor_name)
                        print(f" ✗ Failed ({elapsed:.1f}s)")
        
        print(f"Factor load done: success {success_count}, failed {fail_count} | "
              f"H5 cache {cache_location_hit_count}, MD5 cache {cache_hit_count}, computed {compute_count}")
        if renamed_duplicates:
            print(f"  Note: renamed {len(renamed_duplicates)} duplicate factor_name(s) to keep columns unique.")
        if failed_names:
            print(f"  Failed: {', '.join(failed_names)}")
        
        if not results:
            return pd.DataFrame()

        if target_index is not None:
            # Force output on target index to avoid accidental union index expansion.
            result_df = pd.DataFrame(results, index=target_index)
            logger.debug(f"  Result DataFrame: {result_df.shape}")
            return result_df

        # Fallback: original behavior when we can't determine a target index.
        aligned_results: Dict[str, pd.Series] = {}
        reference_index = None
        for name, series in results.items():
            if reference_index is None:
                reference_index = series.index
            validated = self._validate_and_align_result(series, name, reference_index)
            if validated is not None:
                aligned_results[name] = validated
        if aligned_results:
            result_df = pd.DataFrame(aligned_results)
            logger.debug(f"  Result DataFrame: {result_df.shape}")
            return result_df

        return pd.DataFrame()
    
    def _validate_and_align_result(self, result: pd.Series, factor_name: str, 
                                    reference_index: Optional[pd.Index] = None) -> Optional[pd.Series]:
        """Validate and align cached result index."""
        if result is None:
            return None
        
        target_idx = reference_index
        if target_idx is None:
            try:
                target_idx = self.data_df.index
            except Exception:
                return result if len(result) > 0 and not result.isna().all() else None
        
        # Align index (duplicate-safe)
        if not result.index.equals(target_idx):
            try:
                if result.index.duplicated().any():
                    result = result[~result.index.duplicated(keep='last')]
                if target_idx.duplicated().any():
                    target_idx = target_idx[~target_idx.duplicated(keep='last')]
                
                common_idx = result.index.intersection(target_idx)
                if len(common_idx) > len(target_idx) * 0.5:
                    result = result.reindex(target_idx)
                    logger.debug(f"    Index align: common {len(common_idx)}, target {len(target_idx)}")
                else:
                    logger.warning(f"    Cache index match rate too low ({len(common_idx)}/{len(target_idx)}), will recompute")
                    return None
            except Exception as e:
                logger.warning(f"    Index align failed: {e}, will recompute")
                return None
        
        # Validate data
        if result is None or len(result) == 0 or result.isna().all():
            return None
        
        return result


class CustomFactorDataLoader:
    """
    Converts computed factor values to Qlib-compatible format.
    """
    
    def __init__(self, factor_df: pd.DataFrame, label_expr: str = "Ref($close, -2) / Ref($close, -1) - 1"):
        self.factor_df = factor_df
        self.label_expr = label_expr
        
    def to_qlib_format(self, data_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Convert to Qlib data format."""
        from quantaalpha.factors.coder.expr_parser import (
            parse_expression, parse_symbol
        )
        import quantaalpha.factors.coder.function_lib as func_lib
        
        df = data_df.copy()
        
        expr = parse_symbol(self.label_expr, df.columns)
        expr = parse_expression(expr)
        
        for col in df.columns:
            if col.startswith('$'):
                expr = expr.replace(col[1:], f"df['{col}']")
        
        exec_globals = {'df': df, 'np': np, 'pd': pd}
        for name in dir(func_lib):
            if not name.startswith('_'):
                obj = getattr(func_lib, name)
                if callable(obj):
                    exec_globals[name] = obj
        
        label = eval(expr, exec_globals)
        if isinstance(label, pd.DataFrame):
            label = label.iloc[:, 0]
        
        labels_df = pd.DataFrame({'LABEL0': label})
        
        return self.factor_df, labels_df


def get_qlib_stock_data(config: Dict) -> pd.DataFrame:
    """Load stock data from Qlib."""
    import qlib
    from qlib.data import D
    
    data_config = config.get('data', {})
    
    # Prefer QLIB_DATA_DIR env (aligned with runner.py)
    provider_uri = (
        os.environ.get('QLIB_DATA_DIR')
        or os.environ.get('QLIB_PROVIDER_URI')
        or data_config.get('provider_uri', os.path.expanduser('~/.qlib/qlib_data/cn_data'))
    )
    provider_uri = os.path.expanduser(provider_uri)
    region = data_config.get('region', 'cn')
    
    try:
        qlib.init(provider_uri=provider_uri, region=region)
    except Exception:
        pass  # Already initialized
    
    start_time = data_config.get('start_time', '2016-01-01')
    end_time = data_config.get('end_time', '2025-12-31')
    market = data_config.get('market', 'csi300')
    
    stock_list = D.instruments(market)
    
    fields = ['$open', '$high', '$low', '$close', '$volume', '$vwap']
    df = D.features(
        stock_list,
        fields,
        start_time=start_time,
        end_time=end_time,
        freq='day'
    )
    
    df.columns = fields

    # Normalize to canonical MultiIndex(datetime, instrument) to match cached factor format
    # and downstream backtest alignment logic.
    if isinstance(df.index, pd.MultiIndex) and df.index.nlevels >= 2:
        expected = ["datetime", "instrument"]
        names = list(df.index.names[:2])
        if names != expected and set(names) == set(expected):
            df = df.swaplevel().sort_index()
        # Ensure stable level names (qlib sometimes uses the same names but different order).
        df.index = df.index.set_names(expected)
    
    logger.debug(f"Loaded stock data: {len(df)} rows")
    
    return df


if __name__ == '__main__':
    """Test factor computation."""
    import yaml
    
    logging.basicConfig(level=logging.INFO)
    
    _project_root = Path(__file__).resolve().parents[2]
    config_path = _project_root / 'configs' / 'backtest.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    print("Loading stock data...")
    data_df = get_qlib_stock_data(config)
    
    calculator = CustomFactorCalculator(data_df)
    
    test_expr = "RANK(-1 * TS_PCTCHANGE($close, 10))"
    print(f"\nTest expression: {test_expr}")
    
    result = calculator.calculate_factor("test_factor", test_expr)
    if result is not None:
        print(f"Success! Result shape: {result.shape}")
        print(result.head())
    else:
        print("Failed!")

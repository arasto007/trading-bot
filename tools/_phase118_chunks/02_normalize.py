def normalize_mt5_export_to_arrays(
    raw_path: Path,
    *,
    out_parquet: Path,
    source_rel: str,
    chunksize: int = CHUNKSIZE,
) -> dict[str, Any]:
    """Chunked parse, quote-state ffill, single parquet. Raw untouched.

    RAW missing bid/ask counts are measured BEFORE forward-fill.
    Normalized layer forward-fills bid/ask within the stream so one-sided MT5
    updates become full quote pairs (carry-forward, not invented ticks).
    """
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = out_parquet.parent / "_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    for old in parts_dir.glob("part_*.parquet"):
        old.unlink()

    reader = pd.read_csv(
        raw_path,
        sep="\t",
        chunksize=chunksize,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
        engine="c",
    )

    last_bid: float | None = None
    last_ask: float | None = None
    n_rows = 0
    missing_bid_raw = 0
    missing_ask_raw = 0
    missing_both_raw = 0
    flags_hist: dict[str, int] = {}
    n_ffill_bid = 0
    n_ffill_ask = 0
    part_paths: list[Path] = []
    part_i = 0
    n_ask_lt_bid_raw = 0

    for chunk in reader:
        chunk.columns = _strip_angle_headers(list(chunk.columns))
        if "date" not in chunk.columns or "time" not in chunk.columns:
            raise ValueError(f"MT5 export missing DATE/TIME columns: {list(chunk.columns)}")

        ts = parse_mt5_datetime_utc(chunk["date"], chunk["time"])
        bid_raw = (
            pd.to_numeric(chunk["bid"], errors="coerce")
            if "bid" in chunk.columns
            else pd.Series(np.nan, index=chunk.index)
        )
        ask_raw = (
            pd.to_numeric(chunk["ask"], errors="coerce")
            if "ask" in chunk.columns
            else pd.Series(np.nan, index=chunk.index)
        )
        last = (
            pd.to_numeric(chunk["last"], errors="coerce")
            if "last" in chunk.columns
            else pd.Series(np.nan, index=chunk.index)
        )
        vol = (
            pd.to_numeric(chunk["volume"], errors="coerce")
            if "volume" in chunk.columns
            else pd.Series(np.nan, index=chunk.index)
        )
        flags = chunk["flags"] if "flags" in chunk.columns else pd.Series([None] * len(chunk), index=chunk.index)

        b_raw = bid_raw.to_numpy(dtype=float, copy=True)
        a_raw = ask_raw.to_numpy(dtype=float, copy=True)
        miss_b = ~np.isfinite(b_raw)
        miss_a = ~np.isfinite(a_raw)
        missing_bid_raw += int(miss_b.sum())
        missing_ask_raw += int(miss_a.sum())
        missing_both_raw += int((miss_b & miss_a).sum())
        both_finite_raw = np.isfinite(b_raw) & np.isfinite(a_raw)
        n_ask_lt_bid_raw += int((both_finite_raw & (a_raw < b_raw)).sum())

        for fl, cnt in flags.value_counts(dropna=False).items():
            key = str(fl)
            flags_hist[key] = flags_hist.get(key, 0) + int(cnt)

        b = b_raw.copy()
        a = a_raw.copy()
        for i in range(len(b)):
            if np.isfinite(b[i]):
                last_bid = float(b[i])
            elif last_bid is not None:
                b[i] = last_bid
                n_ffill_bid += 1
            if np.isfinite(a[i]):
                last_ask = float(a[i])
            elif last_ask is not None:
                a[i] = last_ask
                n_ffill_ask += 1

        spread = np.where(np.isfinite(b) & np.isfinite(a), a - b, np.nan)
        out = pd.DataFrame(
            {
                "timestamp_utc": ts,
                "bid": b,
                "ask": a,
                "last": last.to_numpy(dtype=float),
                "volume": vol.to_numpy(dtype=float),
                "flags": flags.astype(str).to_numpy(),
                "spread": spread,
                "source": source_rel,
                "symbol": CANONICAL_SYMBOL,
            }
        )
        out = out.dropna(subset=["timestamp_utc"]).reset_index(drop=True)
        if len(out) == 0:
            continue
        n_rows += int(len(out))
        part = parts_dir / f"part_{part_i:05d}.parquet"
        out.to_parquet(part, index=False)
        part_paths.append(part)
        part_i += 1
        del chunk, out, ts, bid_raw, ask_raw, last, vol, flags, b, a, b_raw, a_raw, spread

    if not part_paths:
        raise ValueError("No tick rows parsed from operator export")

    frames = [pd.read_parquet(p) for p in part_paths]
    ticks = pd.concat(frames, ignore_index=True)
    del frames
    ticks = ticks.sort_values("timestamp_utc").reset_index(drop=True)
    val = validate_tick_frame(ticks)
    ticks.to_parquet(out_parquet, index=False)

    for p in part_paths:
        p.unlink(missing_ok=True)
    try:
        parts_dir.rmdir()
    except OSError:
        pass

    ts_idx = pd.DatetimeIndex(pd.to_datetime(ticks["timestamp_utc"], utc=True))
    gaps = gap_statistics(ts_idx, weekday_threshold=None)
    days = trading_day_counts(ts_idx)
    finite_spread = ticks["spread"].to_numpy(dtype=float)
    finite_spread = finite_spread[np.isfinite(finite_spread)]
    spread_stats = {
        "n_finite": int(len(finite_spread)),
        "median": float(np.median(finite_spread)) if len(finite_spread) else None,
        "mean": float(np.mean(finite_spread)) if len(finite_spread) else None,
        "p90": float(np.quantile(finite_spread, 0.9)) if len(finite_spread) else None,
        "min": float(np.min(finite_spread)) if len(finite_spread) else None,
        "max": float(np.max(finite_spread)) if len(finite_spread) else None,
        "derived_from": "real bid-ask after quote-state carry-forward; never from OHLC",
    }

    acq_start = pd.Timestamp(ACQ_START_ISO)
    acq_end = pd.Timestamp(ACQ_END_ISO)
    if acq_start.tzinfo is None:
        acq_start = acq_start.tz_localize("UTC")
    if acq_end.tzinfo is None:
        acq_end = acq_end.tz_localize("UTC")
    tmin = ts_idx.min() if len(ts_idx) else None
    tmax = ts_idx.max() if len(ts_idx) else None
    full_window = bool(tmin is not None and tmax is not None and tmin <= acq_start and tmax >= acq_end)

    outlier_ts = pd.Timestamp(OUTLIER_TS)
    if outlier_ts.tzinfo is None:
        outlier_ts = outlier_ts.tz_localize("UTC")
    outlier_cov = bool(tmin is not None and tmax is not None and tmin <= outlier_ts <= tmax)

    return {
        "n_rows": n_rows,
        "actual_first_tick": iso_z(tmin),
        "actual_last_tick": iso_z(tmax),
        "missing_bid_rows_raw": missing_bid_raw,
        "missing_ask_rows_raw": missing_ask_raw,
        "missing_both_rows_raw": missing_both_raw,
        "n_ask_lt_bid_raw": n_ask_lt_bid_raw,
        "n_ffill_bid": n_ffill_bid,
        "n_ffill_ask": n_ffill_ask,
        "quote_carry_forward_note": QUOTE_CARRY_FORWARD_NOTE,
        "flags_histogram": flags_hist,
        "validation_normalized": val,
        "gaps": gaps,
        "days": days,
        "spread_stats": spread_stats,
        "full_window_covered": full_window,
        "OUTLIER_31_84R_COVERAGE": outlier_cov,
        "normalized_path": str(out_parquet),
        "timezone_convention": "MT5 DATE+TIME treated as UTC; end aligns with requested UTC window",
        "ms_precision_present": True,
    }

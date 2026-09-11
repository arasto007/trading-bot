def join_events_to_ticks(
    events: list[dict[str, Any]],
    ticks: pd.DataFrame,
) -> dict[str, Any]:
    """Join 419 events to ticks with asof semantics. Never uses future ticks."""
    if ticks is None or len(ticks) == 0:
        empty_chrono = {c: 0 for c in CHRONOLOGY_CLASSES}
        return {
            "TICK_EVENT_COVERAGE": 0,
            "TICK_COMPLETE_LIFECYCLE_EVENTS": 0,
            "TICK_INTRABAR_RESOLUTION_COVERAGE": 0,
            "AMBIGUOUS_394_RESOLVED": 0,
            "AMBIGUOUS_394_REMAINING": N_AMBIGUOUS_394,
            "ambiguous_394_resolved_by_phase118_export": 0,
            "prior_phase115_resolved_3": PHASE115_RESOLVED_AMBIGUOUS,
            "FAVORABLE_FIRST": 0,
            "ADVERSE_FIRST": 0,
            "SIMULTANEOUS_UNRESOLVED": 0,
            "DATA_INSUFFICIENT": N_EVENTS,
            "EXIT_WITHOUT_INTRABAR_RESOLUTION": 0,
            "chronology_counts": empty_chrono,
            "join_rows": [],
            "path_class_chronology": {},
        }

    ts_ns = ticks["timestamp_utc"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    bid = ticks["bid"].to_numpy(dtype=float)
    ask = ticks["ask"].to_numpy(dtype=float)
    tmin = pd.Timestamp(ticks["timestamp_utc"].min())
    tmax = pd.Timestamp(ticks["timestamp_utc"].max())
    if tmin.tzinfo is None:
        tmin = tmin.tz_localize("UTC")
    else:
        tmin = tmin.tz_convert("UTC")
    if tmax.tzinfo is None:
        tmax = tmax.tz_localize("UTC")
    else:
        tmax = tmax.tz_convert("UTC")
    pad_ns = int(BAR_MINUTES * 60 * 1_000_000_000)

    chrono_counts: dict[str, int] = {c: 0 for c in CHRONOLOGY_CLASSES}
    join_rows: list[dict[str, Any]] = []
    n_life = 0
    n_resolved = 0
    n_amb_resolved = 0
    path_chrono: dict[str, dict[str, int]] = {}

    for ev in events:
        entry = ev.get("entry_timestamp")
        exit_ts = ev.get("exit_timestamp")
        if entry is None:
            chrono_counts["DATA_INSUFFICIENT"] += 1
            join_rows.append(
                {
                    "event_id": ev.get("event_id"),
                    "chronology": "DATA_INSUFFICIENT",
                    "lifecycle_covered": False,
                    "cover_entry": False,
                    "ambiguous_394": bool(ev.get("ambiguous_394")),
                    "path_class": ev.get("path_class"),
                    "entry_in_tick_range": False,
                    "asof_future_leak_at_entry": False,
                }
            )
            continue

        entry_u = enforce_utc(entry)
        exit_u = enforce_utc(exit_ts or entry)
        entry_ns = int(pd.Timestamp(entry_u).value)
        exit_ns = int(pd.Timestamp(exit_u).value)
        cov_entry = _ticks_cover_state(ts_ns, entry, pad_ns)
        cov_exit = _ticks_cover_state(ts_ns, exit_ts, pad_ns)
        in_range = _event_in_range(ev, tmin, tmax)
        life = bool(cov_entry and cov_exit)
        if life:
            n_life += 1

        lo = int(np.searchsorted(ts_ns, entry_ns, side="left"))
        hi = int(np.searchsorted(ts_ns, exit_ns, side="right"))
        sub_ts = ts_ns[lo:hi]
        sub_bid = bid[lo:hi]
        sub_ask = ask[lo:hi]
        entry_px = ev.get("entry_price")
        if len(sub_ts) == 0 or entry_px is None:
            chrono = classify_intrabar_order(
                str(ev.get("side")), float("nan"), np.array([]), np.array([]), np.array([])
            )
        else:
            chrono = classify_intrabar_order(
                str(ev.get("side")),
                float(entry_px),
                sub_ts,
                sub_bid,
                sub_ask,
                exit_ns=exit_ns,
            )
        klass = chrono["class"]
        chrono_counts[klass] = chrono_counts.get(klass, 0) + 1
        resolved = klass in {"FAVORABLE_FIRST", "ADVERSE_FIRST"}
        if resolved:
            n_resolved += 1
            if ev.get("ambiguous_394"):
                n_amb_resolved += 1

        pc = str(ev.get("path_class") or "other")
        if life:
            bucket = path_chrono.setdefault(pc, {c: 0 for c in CHRONOLOGY_CLASSES})
            bucket[klass] = bucket.get(klass, 0) + 1

        i_asof = asof_tick_index(ts_ns, entry_ns)
        future_leak = bool(i_asof >= 0 and int(ts_ns[i_asof]) > entry_ns)

        join_rows.append(
            {
                "event_id": ev.get("event_id"),
                "side": ev.get("side"),
                "path_class": ev.get("path_class"),
                "entry_timestamp": iso_z(entry),
                "exit_timestamp": iso_z(exit_ts),
                "tick_n_in_lifecycle": int(hi - lo),
                "cover_entry": cov_entry,
                "cover_exit": cov_exit,
                "entry_in_tick_range": in_range,
                "lifecycle_covered": life,
                "chronology": klass,
                "same_timestamp_ambiguous": chrono.get("same_timestamp_ambiguous"),
                "ambiguous_394": bool(ev.get("ambiguous_394")),
                "asof_future_leak_at_entry": future_leak,
                "lifecycle_in_range": _lifecycle_in_range(ev, tmin, tmax),
            }
        )

    tick_event_coverage = sum(
        1 for r in join_rows if r.get("entry_in_tick_range") or r.get("cover_entry")
    )
    return {
        "TICK_EVENT_COVERAGE": int(tick_event_coverage),
        "TICK_COMPLETE_LIFECYCLE_EVENTS": int(n_life),
        "TICK_INTRABAR_RESOLUTION_COVERAGE": int(n_resolved),
        "AMBIGUOUS_394_RESOLVED": int(n_amb_resolved),
        "AMBIGUOUS_394_REMAINING": int(N_AMBIGUOUS_394 - n_amb_resolved),
        "ambiguous_394_resolved_by_phase118_export": int(n_amb_resolved),
        "prior_phase115_resolved_3": PHASE115_RESOLVED_AMBIGUOUS,
        "FAVORABLE_FIRST": int(chrono_counts.get("FAVORABLE_FIRST", 0)),
        "ADVERSE_FIRST": int(chrono_counts.get("ADVERSE_FIRST", 0)),
        "SIMULTANEOUS_UNRESOLVED": int(chrono_counts.get("SIMULTANEOUS_UNRESOLVED", 0)),
        "DATA_INSUFFICIENT": int(chrono_counts.get("DATA_INSUFFICIENT", 0)),
        "EXIT_WITHOUT_INTRABAR_RESOLUTION": int(
            chrono_counts.get("EXIT_WITHOUT_INTRABAR_RESOLUTION", 0)
        ),
        "chronology_counts": chrono_counts,
        "join_rows": join_rows,
        "path_class_chronology": path_chrono,
        "tick_first": iso_z(tmin),
        "tick_last": iso_z(tmax),
        "n_events": len(events),
    }


def classify_phase118_statuses(
    *,
    raw_present: bool,
    identity_ok: bool,
    full_window: bool,
    outlier_cov: bool,
    missing_bid_raw: int,
    missing_ask_raw: int,
    n_rows: int,
    ms_precision: bool,
    spread_n: int,
    join: dict[str, Any],
) -> dict[str, Any]:
    source = "VERIFIED" if (raw_present and identity_ok) else ("UNKNOWN" if not raw_present else "BLOCKED")
    hist = "VERIFIED" if full_window else ("PARTIAL" if n_rows else "MISSING")
    bid_ask = "PARTIAL" if n_rows else "MISSING"
    if n_rows and missing_bid_raw == 0 and missing_ask_raw == 0:
        bid_ask = "VERIFIED"
    ts_status = "VERIFIED" if (n_rows and ms_precision) else ("PARTIAL" if n_rows else "MISSING")
    spread = "VERIFIED" if spread_n > 0 and full_window else ("PARTIAL" if spread_n > 0 else "MISSING")
    quality = "VERIFIED" if full_window and identity_ok else ("PARTIAL" if n_rows else "MISSING")

    life = int(join.get("TICK_COMPLETE_LIFECYCLE_EVENTS") or 0)
    if not full_window:
        cd_status = "INSUFFICIENT_FULL_HORIZON" if life == 0 else "PARTIAL"
    else:
        path = join.get("path_class_chronology") or {}
        cdef = sum(sum(v.values()) for k, v in path.items() if k in {"C", "D", "E", "F"})
        cd_status = "PARTIAL" if cdef else "INSUFFICIENT_FULL_HORIZON"

    return {
        "SOURCE_IDENTITY_STATUS": source,
        "HISTORY_RANGE_STATUS": hist,
        "BID_ASK_STATUS": bid_ask,
        "TIMESTAMP_STATUS": ts_status,
        "SPREAD_STATUS": spread,
        "DATA_QUALITY_STATUS": quality,
        "OUTLIER_31_84R_COVERAGE": bool(outlier_cov),
        "OUTLIER_31_84R_CHRONOLOGY_STATUS": "DATA_INSUFFICIENT",
        "C_D_E_F_STATUS": cd_status,
    }


def _outlier_chrono(events: list[dict[str, Any]], join: dict[str, Any]) -> dict[str, Any]:
    f_ev = None
    for e in events:
        r = e.get("r_result")
        try:
            rf = float(r) if r is not None else None
        except (TypeError, ValueError):
            rf = None
        if e.get("path_class") == "F" or (rf is not None and abs(rf - 31.84) < 0.05):
            f_ev = e
            break
    covered = False
    chrono = "DATA_INSUFFICIENT"
    if f_ev is not None:
        for row in join.get("join_rows") or []:
            if row.get("event_id") == f_ev.get("event_id"):
                covered = bool(row.get("lifecycle_covered"))
                chrono = row.get("chronology") or "DATA_INSUFFICIENT"
                break
    return {
        "OUTLIER_31_84R_COVERAGE": bool(covered),
        "OUTLIER_31_84R_CHRONOLOGY_STATUS": chrono if covered else "DATA_INSUFFICIENT",
        "outlier_event_id": None if f_ev is None else f_ev.get("event_id"),
        "outlier_entry": None if f_ev is None else iso_z(f_ev.get("entry_timestamp")),
    }


def _frozen_integrity(root: Path) -> dict[str, Any]:
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    sha = file_sha256(root / PHASE40_SETUPS_JSONL)
    ts = p40.get("timestamp_utc")
    fp = p40.get("tape_fingerprint") or p40.get("fingerprint")
    ok = ts == PHASE40_TS and fp == FROZEN and sha == EXPECTED_JSONL_SHA256
    return {
        "ok": ok,
        "FROZEN_PHASE40_TIMESTAMP": ts,
        "FROZEN_PHASE40_FINGERPRINT": fp,
        "FROZEN_PHASE40_SHA256": sha,
        "expected_timestamp": PHASE40_TS,
        "expected_fingerprint": FROZEN,
        "expected_sha256": EXPECTED_JSONL_SHA256,
        "jsonl_byte_identical": sha == EXPECTED_JSONL_SHA256,
        "repaired": False,
    }

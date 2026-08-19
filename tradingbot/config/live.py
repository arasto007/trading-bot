"""
Live Trading Configuration
=========================
Configuration settings specifically for live trading operations.

MT5 credentials MUST be provided via environment variables:
  MT5_LOGIN, MT5_PASSWORD, MT5_SERVER

See .env.example in project root.
"""

import os
from typing import Dict, Any, List

# Demo broker symbol for every live MT5 path. Canonical PA preset key stays XAUUSD
# via normalize_symbol("XAUUSD_i") → "XAUUSD".
PRIMARY_SYMBOL = "XAUUSD_i"

# Live Trading Configuration
LIVE_TRADING_CONFIG = {
    # MT5 Connection Settings — loaded from environment (see legacy_loader.py)
    'MT5_LOGIN': int(os.environ['MT5_LOGIN']) if os.getenv('MT5_LOGIN') else None,
    'MT5_PASSWORD': os.getenv('MT5_PASSWORD', ''),
    'MT5_SERVER': os.getenv('MT5_SERVER', ''),
    
    # Trading Settings — سقف پرتفوی (هم‌راستا با presetهای M5/M15/H4)
    'MAX_POSITIONS': 3,
    'MAX_OPEN_POSITIONS_TOTAL': 3,
    'MAX_OPEN_POSITIONS_PER_SYMBOL': 2,
    'USE_NEWS_FILTER': True,
    'NEWS_BLACKOUT_MINUTES': 30,
    'DEFAULT_LOT_SIZE': 0.01,
    'MAX_LOT_SIZE': 1.0,
    'MIN_LOT_SIZE': 0.01,
    
    # Risk Management (OPTIMIZED based on professional standards)
    'RISK_PER_TRADE': 0.005,  # ۰.۵٪ — دمو Price Action
    'MAX_DAILY_RISK': 0.04,  # 4% — الگوی FTMO/maker-tung
    'MAX_WEEKLY_RISK': 0.12,  # 12% max weekly risk (REDUCED from 15% - More Conservative)
    'MAX_MONTHLY_RISK': 0.18,  # 18% max monthly risk (REDUCED from 25% - Professional Standard)
    'MAX_CONSECUTIVE_LOSSES': 3,
    'MAX_TRADES_PER_DAY': 5,
    'MAX_TRADES_PER_WEEK': 50,
    
    # Balance Exposure Limits - DISABLED by user request
    # 'RESERVED_BALANCE_PCT': 0.20,
    # 'MAX_EXPOSURE_PCT': 0.70,
    # 'MAX_PER_POSITION_PCT': 0.10,
    # 'WARNING_EXPOSURE_PCT': 0.50,
    # 'CRITICAL_EXPOSURE_PCT': 0.60,
    
    # Position Protection (OPTIMIZED)
    'POSITION_CHECK_INTERVAL': 10,  # Check positions every 10 seconds (OPTIMAL)
    'MAX_POSITION_AGE_HOURS': 24,  # Auto-close positions after 24 hours (OPTIMAL)
    'EMERGENCY_DRAWDOWN': 0.20,  # Emergency close at 20% drawdown (REDUCED from 25% - Safer)
    
    # Trading Symbols and Timeframes — Gold-only Price Action (demo broker symbol)
    'SYMBOLS': [PRIMARY_SYMBOL],
    'symbols': [PRIMARY_SYMBOL],
    'TIMEFRAMES': ['5m', '15m', '4h'],
    
    # Signal Settings — per-TF presets در pa_symbol_tf_presets (M5/M15/H4)
    'MIN_CONFIDENCE': 0.55,
    'EMERGENCY_MAX_LOSS_PIPS': 90,
    'SIGNAL_TIMEOUT': 90,
    
    # Position Management — اسکالپ سریع
    'TRAILING_STOP_ATR_MULTIPLIER': 2.0,
    'STOP_LOSS_ATR_MULTIPLIER': 1.5,
    'TAKE_PROFIT_ATR_MULTIPLIER': 2.5,
    'POSITION_CHECK_INTERVAL': 10,
    'MAX_POSITION_AGE': 1800,
    
    # EOD Close (بستن پوزیشن پایان روز)
    'EOD_CLOSE_ENABLED': True,
    'EOD_HOUR': 23,
    'EOD_MINUTE': 55,
    
    # System Settings
    'LOOP_INTERVAL': 30,
    'MT5_RETRIES': 5,
    'DATA_UPDATE_INTERVAL': 300,  # 5 minutes
    
    # Logging Settings
    'LOG_LEVEL': 'INFO',
    'LOG_TO_FILE': True,
    'LOG_TO_CONSOLE': True,
    'MAX_LOG_SIZE': 10 * 1024 * 1024,  # 10MB
    'MAX_LOG_BACKUPS': 5,
    
    # Email Reporting
    'EMAIL_ENABLED': True,
    'EMAIL_SMTP_SERVER': 'smtp.gmail.com',
    'EMAIL_SMTP_PORT': 587,
    'EMAIL_USERNAME': os.getenv('EMAIL_USERNAME', ''),
    'EMAIL_PASSWORD': os.getenv('EMAIL_PASSWORD', ''),
    'EMAIL_TO': os.getenv('EMAIL_TO', ''),
    'EMAIL_FROM': os.getenv('EMAIL_FROM', ''),
    
    # Performance Tracking
    'PERFORMANCE_TRACKING': True,
    'PERFORMANCE_REPORT_INTERVAL': 3600,  # 1 hour
    
    # Safety Settings (OPTIMIZED - More Conservative)
    'DEMO_MODE': True,
    # Phase 50A: lock live bot to PA+Meta only — VOL/Adaptive log-only, never selected.
    'PA_PRODUCTION_LOCK': os.getenv('PA_PRODUCTION_LOCK', 'true').lower() in ('1', 'true', 'yes'),
    # DEMO TEST ONLY — bypasses London/NY session windows. Re-enable before live/prop.
    'DEMO_DISABLE_SESSION_FILTER': os.getenv('DEMO_DISABLE_SESSION_FILTER', 'false').lower() in ('1', 'true', 'yes'),
    'VOL_REGIME_ENABLED': os.getenv('VOL_REGIME_ENABLED', 'false').lower() in ('1', 'true', 'yes'),
    # Confluence: VOL_REGIME + MTF must agree — fewer trades, higher quality.
    'ADAPTIVE_CONFLUENCE_ONLY': os.getenv('ADAPTIVE_CONFLUENCE_ONLY', 'true').lower() in ('1', 'true', 'yes'),
    # Phase 44B: OR = MTF or VOL sufficient; AND = both must agree (legacy).
    'ADAPTIVE_CONFLUENCE_MODE': os.getenv('ADAPTIVE_CONFLUENCE_MODE', 'OR').upper(),
    # Phase 4A: quality scoring engine (backtest-only default — set true to opt-in live).
    'ADAPTIVE_QUALITY_ENGINE': os.getenv('ADAPTIVE_QUALITY_ENGINE', 'false').lower() in ('1', 'true', 'yes'),
    # Phase 41D: block all HIGH_VOLATILITY signals on MICRO accounts (rollback via env=false).
    'DISABLE_HIGH_VOL_FOR_MICRO': os.getenv('DISABLE_HIGH_VOL_FOR_MICRO', 'true').lower() in ('1', 'true', 'yes'),
    # Phase 46C/47B: PA → VOL → Adaptive multi-engine router (PA-primary live default).
    'MULTI_ENGINE_ROUTER_ENABLED': os.getenv('MULTI_ENGINE_ROUTER_ENABLED', 'true').lower() in ('1', 'true', 'yes'),
    # Phase 47A calibrated M5 meta threshold (preset fallback when unset).
    'META_LABEL_THRESHOLD': float(os.getenv('META_LABEL_THRESHOLD', '0.38')),
    # Phase 20Y-3 observer path is wired. Default OFF: 30d observer book is unprofitable.
    'META_OBSERVER_MODE': os.getenv('META_OBSERVER_MODE', 'false').lower() in ('1', 'true', 'yes'),
    # Phase 48A: VOL as PA direction filter (not trade engine). 60d test → keep OFF.
    'VOL_DIRECTION_FILTER_ENABLED': os.getenv('VOL_DIRECTION_FILTER_ENABLED', 'false').lower() in ('1', 'true', 'yes'),
    # overstates XAUUSD spread vs live tick — skip TQ so signals reach RiskGate.
    'VOL_REGIME_SKIP_TQ': os.getenv('VOL_REGIME_SKIP_TQ', 'true').lower() in ('1', 'true', 'yes'),
    'VOL_REGIME_CONFIG_ID': 'ATR2.5_RR0.8',
    'VOL_REGIME_ATR_SL_MULT': 2.5,
    'VOL_REGIME_TP_RR': 0.8,
    'VOL_REGIME_MAX_LOT': 0.01,
    'VOL_REGIME_RISK_PER_TRADE_PCT': 0.5,
    'VOL_REGIME_DAILY_KILL_SWITCH_PCT': 2.0,
    'VOL_REGIME_MAX_CONCURRENT': 1,
    'VOL_REGIME_COOLDOWN_BARS': 12,
    'VOL_REGIME_MAX_TRADES_PER_DAY': 3,
    'EMERGENCY_STOP_ENABLED': True,
    'EMERGENCY_STOP_CONDITIONS': {
        'max_drawdown': 0.15,
        'max_consecutive_losses': 3,
        'max_daily_loss': 0.04,
    },
    
    # Optimization Settings
    'NIGHTLY_OPTIMIZATION': True,
    'OPTIMIZATION_TIME': '00:00',  # Midnight
    'ADAPTIVE_OPTIMIZATION': True,
    'OPTIMIZATION_INTERVAL': 24 * 60 * 60,  # 24 hours
    
    # Data Storage
    'DATA_STORAGE_ENABLED': True,
    'DATA_BACKUP_ENABLED': True,
    'DATA_RETENTION_DAYS': 30,
    
    # Monitoring
    'HEALTH_CHECK_INTERVAL': 300,  # 5 minutes
    'ALERT_ON_ERRORS': True,
    'ALERT_ON_RISK_BREACH': True,
}

# Phase 20Y-3 observer is wired. Live default OFF until quality cert passes.
META_OBSERVER_MODE = bool(LIVE_TRADING_CONFIG.get('META_OBSERVER_MODE', False))

# Strategy-specific configurations (REMOVED - strategies have their own parameters)
# استراتژی‌ها پارامترهای خودشون رو در فایل‌های مربوطه دارن
STRATEGY_CONFIGS = {}

# Timeframe-specific configurations (ULTRA AGGRESSIVE - Maximum signals)
TIMEFRAME_CONFIGS = {
    '1m': {
        'min_data_points': 80,
        'signal_strength_threshold': 0.45,
        'position_size_multiplier': 0.7,
    },
    '5m': {
        'min_data_points': 50,               # REDUCED - Faster to start
        'signal_strength_threshold': 0.50,   # VERY LOW - Maximum signals
        'position_size_multiplier': 0.8,     # Smaller for scalping
    },
    '15m': {
        'min_data_points': 30,               # REDUCED - Faster to start
        'signal_strength_threshold': 0.52,   # VERY LOW - Maximum signals
        'position_size_multiplier': 1.0,
    },
    '1h': {
        'min_data_points': 20,               # REDUCED - Faster to start
        'signal_strength_threshold': 0.55,   # VERY LOW - Maximum signals
        'position_size_multiplier': 1.2,
    },
    '4h': {
        'min_data_points': 10,               # REDUCED - Faster to start
        'signal_strength_threshold': 0.58,   # VERY LOW - Maximum signals
        'position_size_multiplier': 1.5,
    }
}

# Symbol-specific configurations — فقط طلا (canonical + demo broker alias)
_GOLD_SYMBOL_CFG = {
    'spread_threshold': 0.50,
    'volatility_adjustment': 1.2,
    'preferred_timeframes': ['5m', '15m', '4h'],
}
SYMBOL_CONFIGS = {
    'XAUUSD': _GOLD_SYMBOL_CFG,
    PRIMARY_SYMBOL: _GOLD_SYMBOL_CFG,
}

def get_live_config() -> Dict[str, Any]:
    """Get live trading configuration."""
    from tradingbot.config.prop_presets import apply_prop_preset

    cfg = apply_prop_preset(LIVE_TRADING_CONFIG.copy())
    # PA-primary / adaptive / VOL live kernel is M5-only on XAUUSD.
    if (
        cfg.get("ADAPTIVE_REGIME_ENABLED")
        or cfg.get("VOL_REGIME_ENABLED")
        or cfg.get("MULTI_ENGINE_ROUTER_ENABLED")
    ):
        cfg["TIMEFRAMES"] = ["5m"]
        cfg["SYMBOLS"] = [PRIMARY_SYMBOL]
        cfg["symbols"] = [PRIMARY_SYMBOL]
    return cfg

def get_strategy_config(strategy_name: str) -> Dict[str, Any]:
    """Get strategy-specific configuration."""
    return STRATEGY_CONFIGS.get(strategy_name, {})

def get_timeframe_config(timeframe: str) -> Dict[str, Any]:
    """Get timeframe-specific configuration."""
    return TIMEFRAME_CONFIGS.get(timeframe, {})

def get_symbol_config(symbol: str) -> Dict[str, Any]:
    """Get symbol-specific configuration."""
    return SYMBOL_CONFIGS.get(symbol, {})

def validate_config(config: Dict[str, Any]) -> List[str]:
    """Validate configuration and return list of issues."""
    issues = []
    
    # Check required fields
    required_fields = ['MT5_LOGIN', 'MT5_PASSWORD', 'MT5_SERVER']
    for field in required_fields:
        if not config.get(field) or config[field] == f'your_{field.lower()}_here':
            issues.append(f"Missing or invalid {field}")
    
    # Check risk settings
    if config.get('RISK_PER_TRADE', 0) > 0.05:
        issues.append("RISK_PER_TRADE is too high (>5%)")
    
    if config.get('MAX_DAILY_RISK', 0) > 0.10:
        issues.append("MAX_DAILY_RISK is too high (>10%)")
    
    # Check lot sizes
    if config.get('DEFAULT_LOT_SIZE', 0) < 0.01:
        issues.append("DEFAULT_LOT_SIZE is too small (<0.01)")
    
    if config.get('MAX_LOT_SIZE', 0) > 10.0:
        issues.append("MAX_LOT_SIZE is too large (>10.0)")
    
    # Check symbols and timeframes
    if not config.get('SYMBOLS'):
        issues.append("No trading symbols configured")
    
    if not config.get('TIMEFRAMES'):
        issues.append("No timeframes configured")
    
    return issues

def print_config_summary(config: Dict[str, Any]):
    """Print configuration summary."""
    print("[CLIPBOARD] Live Trading Configuration Summary:")
    print("=" * 50)
    print(f"🔗 MT5 Server: {config.get('MT5_SERVER', 'Not configured')}")
    print(f"👤 Login: {config.get('MT5_LOGIN', 'Not configured')}")
    print(f"[TARGET] Demo Mode: {config.get('DEMO_MODE', True)}")
    print(f"[MONEY] Default Lot Size: {config.get('DEFAULT_LOT_SIZE', 0.01)}")
    print(f"🛡️ Risk Per Trade: {config.get('RISK_PER_TRADE', 0.02) * 100:.1f}%")
    print(f"[DATA] Symbols: {', '.join(config.get('SYMBOLS', []))}")
    print(f"[TIME] Timeframes: {', '.join(config.get('TIMEFRAMES', []))}")
    print(f"[TARGET] Min Confidence: {config.get('MIN_CONFIDENCE', 0.65)}")
    print(f"[REFRESH] Loop Interval: {config.get('LOOP_INTERVAL', 60)}s")
    print("=" * 50)

if __name__ == "__main__":
    # Test configuration
    config = get_live_config()
    issues = validate_config(config)
    
    if issues:
        print("[ERROR] Configuration Issues:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("[SUCCESS] Configuration is valid")
    
    print_config_summary(config)

"""
TradingBot Configuration Module
===============================
Clean, organized, and maintainable configuration system following SOLID principles.
"""

import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import json
try:
    import yaml  # pyright: ignore[reportMissingModuleSource]
except ImportError:
    yaml = None
from enum import Enum

# =============================================================================
# ENUMS AND CONSTANTS
# =============================================================================

class TimeFrame(Enum):
    """Trading timeframes enumeration."""
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

class TradingMode(Enum):
    """Trading modes enumeration."""
    LIVE = "live"
    BACKTEST = "backtest"
    PAPER = "paper"

# =============================================================================
# CONFIGURATION INTERFACES
# =============================================================================

class IConfigurationProvider(ABC):
    """Abstract interface for configuration providers."""
    
    @abstractmethod
    def get_config(self) -> Dict[str, Any]:
        """Get configuration dictionary."""
        pass
    
    @abstractmethod
    def validate(self) -> bool:
        """Validate configuration."""
        pass

# =============================================================================
# CONFIGURATION DATA CLASSES
# =============================================================================

@dataclass
class MT5Config:
    """MetaTrader5 configuration."""
    login: int
    password: str
    server: str
    retries: int = 5
    default_filling_mode: int = 2  # ORDER_FILLING_FOK
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "login": self.login,
            "password": self.password,
            "server": self.server,
            "retries": self.retries,
            "default_filling_mode": self.default_filling_mode
        }

@dataclass
class EmailConfig:
    """Email configuration."""
    sender: str
    password: str
    receiver: str
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender": self.sender,
            "email_password": self.password,
            "receiver": self.receiver,
            "smtp_server": self.smtp_server,
            "smtp_port": self.smtp_port
        }

@dataclass
class StorageConfig:
    """Storage configuration."""
    base_path: Path
    data_path: Path = field(init=False)
    reports_path: Path = field(init=False)
    models_path: Path = field(init=False)
    logs_path: Path = field(init=False)
    
    def __post_init__(self):
        self.data_path = self.base_path / "data"
        self.reports_path = self.base_path / "reports"
        self.models_path = self.base_path / "saved_models"
        self.logs_path = self.base_path / "logs"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_path": str(self.base_path),
            "data_path": str(self.data_path),
            "reports_path": str(self.reports_path),
            "models_path": str(self.models_path),
            "logs_path": str(self.logs_path)
        }

@dataclass
class TradingConfig:
    """Trading configuration."""
    max_open_positions: int = 4
    default_lot_size: float = 0.01
    min_lot: float = 0.01
    max_lot: float = 0.3
    loop_interval: int = 60
    max_gap_minutes: int = 60
    max_spread: int = 50
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_open_positions": self.max_open_positions,
            "default_lot_size": self.default_lot_size,
            "min_lot": self.min_lot,
            "max_lot": self.max_lot,
            "loop_interval": self.loop_interval,
            "max_gap_minutes": self.max_gap_minutes,
            "max_spread": self.max_spread
        }

@dataclass
class RiskConfig:
    """Risk management configuration - بهبود شده برای سود مثبت."""
    risk_per_trade: float = 0.005   # 0.5% per trade - کاهش برای ریسک کمتر
    max_daily_loss: float = 0.25    # 25% daily - افزایش برای انعطاف بیشتر
    max_weekly_loss: float = 0.40   # 40% weekly - افزایش برای انعطاف بیشتر
    max_monthly_loss: float = 0.60  # 60% monthly - افزایش برای انعطاف بیشتر
    max_daily_trades: int = 100     # افزایش برای معاملات بیشتر
    max_weekly_trades: int = 200   # افزایش یافت
    max_consecutive_losses: int = 10  # افزایش یافت
    max_drawdown: float = 0.40     # افزایش یافت
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_per_trade": self.risk_per_trade,
            "max_daily_loss": self.max_daily_loss,
            "max_weekly_loss": self.max_weekly_loss,
            "max_monthly_loss": self.max_monthly_loss,
            "max_daily_trades": self.max_daily_trades,
            "max_weekly_trades": self.max_weekly_trades,
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_drawdown": self.max_drawdown
        }

@dataclass
class MLConfig:
    """Machine learning configuration."""
    confidence_threshold: float = 0.65
    min_signals: int = 2
    use_ensemble: bool = True
    signal_weight: float = 0.8
    ensemble_confidence_threshold: float = 0.75
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "confidence_threshold": self.confidence_threshold,
            "min_signals": self.min_signals,
            "use_ensemble": self.use_ensemble,
            "signal_weight": self.signal_weight,
            "ensemble_confidence_threshold": self.ensemble_confidence_threshold
        }

@dataclass
class TechnicalConfig:
    """Technical indicators configuration."""
    use_atr_for_size: bool = True
    atr_multiplier: float = 2.0
    atr_period: int = 14
    min_atr: float = 0.0001
    max_atr: float = 0.01
    stop_loss_multiplier: float = 2.0
    take_profit_multiplier: float = 2.5
    trailing_stop_multiplier: float = 1.5
    breakeven_threshold: float = 0.5
    partial_close_threshold: float = 0.7
    partial_close_ratio: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "use_atr_for_size": self.use_atr_for_size,
            "atr_multiplier": self.atr_multiplier,
            "atr_period": self.atr_period,
            "min_atr": self.min_atr,
            "max_atr": self.max_atr,
            "stop_loss_multiplier": self.stop_loss_multiplier,
            "take_profit_multiplier": self.take_profit_multiplier,
            "trailing_stop_multiplier": self.trailing_stop_multiplier,
            "breakeven_threshold": self.breakeven_threshold,
            "partial_close_threshold": self.partial_close_threshold,
            "partial_close_ratio": self.partial_close_ratio
}

# =============================================================================
# MAIN CONFIGURATION CLASS
# =============================================================================

class TradingBotConfig(IConfigurationProvider):
    """
    Main configuration class for TradingBot.
    
    This class follows the Single Responsibility Principle by only handling configuration.
    It's open for extension (new config types) but closed for modification.
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration.
        
        Args:
            config_file: Optional path to configuration file
        """
        self.config_file = config_file
        self._base_dir = self._get_base_directory()
        
        # Initialize configuration sections
        self.mt5_config = self._create_mt5_config()
        self.email_config = self._create_email_config()
        self.storage_config = self._create_storage_config()
        self.trading_config = self._create_trading_config()
        self.risk_config = self._create_risk_config()
        self.ml_config = self._create_ml_config()
        self.technical_config = self._create_technical_config()
        
        # Load from file if provided
        if config_file and os.path.exists(config_file):
            self._load_from_file(config_file)
        
        # Validate configuration
        if not self.validate():
            raise ValueError("Configuration validation failed")
    
    def _get_base_directory(self) -> Path:
        """Get base directory for the project."""
        # Try to get from environment variable first
        base_dir = os.getenv('TRADING_BOT_BASE_DIR')
        if base_dir:
            return Path(base_dir)
        
        # Fallback to current working directory
        return Path.cwd()
    
    def _create_mt5_config(self) -> MT5Config:
        """Create MT5 configuration from environment or defaults."""
        return MT5Config(
            login=int(os.getenv('MT5_LOGIN', '90816536')),
            password=os.getenv('MT5_PASSWORD', 'Amir@11067497'),
            server=os.getenv('MT5_SERVER', 'LiteFinance-MT5-Demo'),
            retries=int(os.getenv('MT5_RETRIES', '5'))
        )
    
    def _create_email_config(self) -> EmailConfig:
        """Create email configuration from environment or defaults."""
        return EmailConfig(
            sender=os.getenv('EMAIL_SENDER', ''),
            password=os.getenv('EMAIL_PASSWORD', ''),
            receiver=os.getenv('EMAIL_RECEIVER', '')
        )
    
    def _create_storage_config(self) -> StorageConfig:
        """Create storage configuration."""
        return StorageConfig(base_path=self._base_dir)
    
    def _create_trading_config(self) -> TradingConfig:
        """Create trading configuration."""
        return TradingConfig()
    
    def _create_risk_config(self) -> RiskConfig:
        """Create risk configuration."""
        return RiskConfig()
    
    def _create_ml_config(self) -> MLConfig:
        """Create ML configuration."""
        return MLConfig()
    
    def _create_technical_config(self) -> TechnicalConfig:
        """Create technical configuration."""
        return TechnicalConfig()
    
    def _load_from_file(self, config_file: str) -> None:
        """Load configuration from file."""
        try:
            file_ext = Path(config_file).suffix.lower()
            
            if file_ext == '.json':
                with open(config_file, 'r') as f:
                    data = json.load(f)
            elif file_ext in ['.yml', '.yaml']:
                if yaml is None:
                    raise ValueError("YAML support not available. Please install PyYAML: pip install PyYAML")
                with open(config_file, 'r') as f:
                    data = yaml.safe_load(f)
            else:
                raise ValueError(f"Unsupported configuration file format: {file_ext}")
            
            # Update configurations with file data
            self._update_configs_from_dict(data)
            
        except Exception as e:
            raise ValueError(f"Failed to load configuration file: {e}")
    
    def _update_configs_from_dict(self, data: Dict[str, Any]) -> None:
        """Update configuration objects from dictionary."""
        # Update MT5 config
        if 'mt5' in data:
            for key, value in data['mt5'].items():
                if hasattr(self.mt5_config, key):
                    setattr(self.mt5_config, key, value)
        
        # Update other configs similarly
        config_mappings = {
            'email': self.email_config,
            'trading': self.trading_config,
            'risk': self.risk_config,
            'ml': self.ml_config,
            'technical': self.technical_config
        }
        
        for config_key, config_obj in config_mappings.items():
            if config_key in data:
                for key, value in data[config_key].items():
                    if hasattr(config_obj, key):
                        setattr(config_obj, key, value)
    
    def get_config(self) -> Dict[str, Any]:
        """Get complete configuration dictionary."""
        from tradingbot.config.live import PRIMARY_SYMBOL

        config_dict = {
            "BASE_DIR": str(self._base_dir),
        "symbols": [PRIMARY_SYMBOL],
        "timeframes": ["5m", "15m", "1h"],
            "min_confidence": self.ml_config.confidence_threshold,
            
            # Merge all configurations
            **self.mt5_config.to_dict(),
            **self.email_config.to_dict(),
            **self.storage_config.to_dict(),
            **self.trading_config.to_dict(),
            **self.risk_config.to_dict(),
            **self.ml_config.to_dict(),
            **self.technical_config.to_dict(),
            
            # Strategy configurations
            "strategy_params": self._get_strategy_params(),
            "strategy_timeframes": self._get_strategy_timeframes(),
            "symbol_filters": self._get_symbol_filters()
        }
        
        return config_dict
    
    def _get_strategy_params(self) -> Dict[str, Any]:
        """Get base strategy parameters."""
        return {
            "rsi_window": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "adx_window": 14,
            "atr_window": 14,
            "sma_window": 50,
            "roc_period": 12,
            "z_score_window": 20
        }

    def _get_strategy_timeframes(self) -> Dict[str, List[str]]:
        """Get strategy timeframe restrictions based on trading research and best practices."""
        return {
    # Scalping Strategies (High Frequency, Low Latency)
    "arbitrage": ["5m", "15m"],                    # Statistical arbitrage works best on short timeframes
    "scalping": ["5m", "15m"],                     # Scalping requires quick execution
    "news_event": ["5m", "15m"],                   # News events need immediate response
    
    # Mean Reversion Strategies (Short to Medium Term)
    "mean_reversion": ["5m", "15m", "1h"],         # Mean reversion works across multiple timeframes
    "classic": ["5m", "15m", "1h"],                # Classic strategies benefit from multiple timeframes
    "ml": ["5m", "15m", "1h"],                     # ML strategies need data from multiple timeframes
    "advanced_ml": ["5m", "15m", "1h"],            # Advanced ML requires more data points
    "simple": ["5m", "15m", "1h"],                 # Simple strategies work on short-medium timeframes
    
    # Trend Following Strategies (Medium to Long Term)
    "trend_following": ["15m", "1h", "4h"],        # Trend following needs longer timeframes
    "momentum": ["15m", "1h", "4h"],               # Momentum strategies work on medium timeframes
    "breakout": ["15m", "1h", "4h"],               # Breakouts need confirmation on higher timeframes
    "volatility_breakout": ["15m", "1h", "4h"],    # Volatility strategies need medium timeframes
    
    # Position Trading Strategies (Long Term)
    "range_bound": ["1h", "4h", "1d"],             # Range trading works on longer timeframes
    
    # Multi-Timeframe Strategies (All Timeframes)
    "multi_timeframe": ["5m", "15m", "1h", "4h"],  # Multi-timeframe needs all timeframes
    "always_trade": ["5m", "15m", "1h", "4h"],     # Always trade strategy uses all timeframes
    
    # Specialized Strategies
    "grid_trading": ["5m", "15m"],                 # Grid trading works on short timeframes
    "pullback": ["5m", "15m", "1h"],               # Pullback strategies need short-medium timeframes
    "pattern_recognition": ["5m", "15m", "1h"],    # Pattern recognition works on multiple timeframes
    "dynamic_sizing": ["5m", "15m", "1h"],         # Dynamic sizing needs multiple timeframes
    "trend_momentum_combo": ["15m", "1h", "4h"],   # Trend-momentum combo needs medium timeframes
    "priceaction": ["5m", "15m", "4h"],
    "price_action": ["5m", "15m", "4h"],
}

    def _get_symbol_filters(self) -> Dict[str, Dict[str, Any]]:
        """Get symbol-specific filters."""
        return {
    "XAUUSD_i": {
        "max_spread": 0.0200,  # طلا spread خیلی بیشتر دارد
        "max_gap_minutes": 240,  # طلا گپ‌های بیشتری دارد
        "min_confidence": 0.62,
        "min_volume": 2,  # طلا volume کمتر
        "min_atr": 0.5,  # طلا ATR بالاتری دارد
        "active_timezones": list(range(1, 24))  # طلا 24 ساعته فعال است
    }
        }
    
    def validate(self) -> bool:
        """Validate configuration."""
        try:
            # Create necessary directories
            directories = [
                self.storage_config.data_path,
                self.storage_config.reports_path,
                self.storage_config.models_path,
                self.storage_config.logs_path
            ]
            
            for directory in directories:
                directory.mkdir(parents=True, exist_ok=True)
            
            return True

        except Exception as e:
            print(f"Configuration validation failed: {e}")
            return False
    
    def save_to_file(self, file_path: str) -> None:
        """Save configuration to file."""
        try:
            config_data = {
                "mt5": self.mt5_config.to_dict(),
                "email": self.email_config.to_dict(),
                "trading": self.trading_config.to_dict(),
                "risk": self.risk_config.to_dict(),
                "ml": self.ml_config.to_dict(),
                "technical": self.technical_config.to_dict()
            }
            
            file_ext = Path(file_path).suffix.lower()
            
            if file_ext == '.json':
                with open(file_path, 'w') as f:
                    json.dump(config_data, f, indent=2)
            elif file_ext in ['.yml', '.yaml']:
                if yaml is None:
                    raise ValueError("YAML support not available. Please install PyYAML: pip install PyYAML")
                with open(file_path, 'w') as f:
                    yaml.dump(config_data, f, default_flow_style=False)
            else:
                raise ValueError(f"Unsupported file format: {file_ext}")
                
        except Exception as e:
            raise ValueError(f"Failed to save configuration: {e}")

# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_config(config_file: Optional[str] = None) -> TradingBotConfig:
    """
    Factory function to create configuration instance.
    
    Args:
        config_file: Optional path to configuration file
        
    Returns:
        TradingBotConfig instance
    """
    return TradingBotConfig(config_file)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

# Global config instance for backward compatibility
config = create_config()

if __name__ == "__main__":
    try:
        print("Configuration created successfully")
        print(f"Base directory: {config._base_dir}")
        print(f"MT5 server: {config.mt5_config.server}")
        
    except Exception as e:
        print(f"Configuration creation failed: {e}")
        exit(1)
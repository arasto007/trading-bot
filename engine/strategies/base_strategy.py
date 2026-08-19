"""
Base Strategy Class
==================
Base class for all trading strategies with common functionality.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from engine.logger import get_logger

logger = get_logger("base_strategy", ".")

class SignalType(Enum):
    """Signal types for trading."""
    BUY = 1
    SELL = -1
    HOLD = 0

class SignalStrength(Enum):
    """Signal strength levels."""
    WEAK = 1
    MEDIUM = 2
    STRONG = 3

class PatternType(Enum):
    """Candlestick pattern types."""
    PIN_BAR = "pin_bar"
    HAMMER = "hammer"
    DOJI = "doji"
    ENGULFING = "engulfing"
    INSIDE_BAR = "inside_bar"
    OUTSIDE_BAR = "outside_bar"
    TWEEZER_TOP = "tweezer_top"
    TWEEZER_BOTTOM = "tweezer_bottom"
    THREE_WHITE_SOLDIERS = "three_white_soldiers"
    THREE_BLACK_CROWS = "three_black_crows"

class Signal:
    """Trading signal class."""
    
    def __init__(self, timestamp: datetime, signal_type: SignalType, 
                 price: float, confidence: float = 0.5, metadata: Dict[str, Any] = None):
        """
        Initialize trading signal.
        
        Args:
            timestamp: Signal timestamp
            signal_type: Type of signal (BUY, SELL, HOLD)
            price: Price at signal time
            confidence: Signal confidence (0-1)
            metadata: Additional signal metadata
        """
        self.timestamp = timestamp
        self.signal_type = signal_type
        self.price = price
        self.confidence = confidence
        self.metadata = metadata or {}
    
    def __str__(self) -> str:
        """String representation of signal."""
        return f"Signal({self.signal_type.name}, {self.price}, {self.confidence:.2f})"
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return f"Signal(timestamp={self.timestamp}, type={self.signal_type.name}, price={self.price}, confidence={self.confidence})"

class BaseStrategy(ABC):
    """
    Base class for all trading strategies.
    
    This class provides common functionality for all strategies including:
    - Signal generation interface
    - Performance tracking
    - Parameter management
    - Logging
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize base strategy.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.name = "Base Strategy"
        self.description = "Base strategy class"
        self.signal_history = []
        self.performance_metrics = {}
        
        # Strategy parameters
        self.min_confidence = config.get('min_confidence', 0.5)
        self.max_position_size = config.get('max_position_size', 0.1)
        self.stop_loss_pct = config.get('stop_loss_pct', 0.02)
        self.take_profit_pct = config.get('take_profit_pct', 0.04)
        
        # Performance tracking
        self.total_signals = 0
        self.buy_signals = 0
        self.sell_signals = 0
        self.winning_signals = 0
        self.losing_signals = 0
        
        logger.info(f"Initialized {self.name}")
    
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame, symbol: str = None, 
                        timeframe: str = None) -> List[Signal]:
        """
        Generate trading signals based on market data.
        
        Args:
            data: Market data DataFrame
            symbol: Trading symbol
            timeframe: Timeframe
            
        Returns:
            List of trading signals
        """
        pass
    
    def validate_signal(self, signal: Signal) -> bool:
        """
        Validate trading signal.
        
        Args:
            signal: Trading signal to validate
            
        Returns:
            True if signal is valid, False otherwise
        """
        try:
            # Check signal type
            if not isinstance(signal.signal_type, SignalType):
                logger.warning(f"Invalid signal type: {signal.signal_type}")
                return False
            
            # Check confidence
            if not 0 <= signal.confidence <= 1:
                logger.warning(f"Invalid confidence: {signal.confidence}")
                return False
            
            # Check price
            if signal.price <= 0:
                logger.warning(f"Invalid price: {signal.price}")
                return False
            
            # Check timestamp
            if not isinstance(signal.timestamp, datetime):
                logger.warning(f"Invalid timestamp: {signal.timestamp}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating signal: {e}")
            return False
    
    def add_signal(self, signal: Signal) -> None:
        """
        Add signal to history.
        
        Args:
            signal: Trading signal to add
        """
        try:
            if self.validate_signal(signal):
                self.signal_history.append(signal)
                self.total_signals += 1
                
                if signal.signal_type == SignalType.BUY:
                    self.buy_signals += 1
                elif signal.signal_type == SignalType.SELL:
                    self.sell_signals += 1
                
                logger.debug(f"Added signal: {signal}")
            else:
                logger.warning(f"Invalid signal rejected: {signal}")
                
        except Exception as e:
            logger.error(f"Error adding signal: {e}")
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get strategy performance metrics.
        
        Returns:
            Dictionary with performance metrics
        """
        try:
            if not self.signal_history:
                return {}
            
            # Calculate basic metrics
            total_signals = len(self.signal_history)
            buy_signals = sum(1 for s in self.signal_history if s.signal_type == SignalType.BUY)
            sell_signals = sum(1 for s in self.signal_history if s.signal_type == SignalType.SELL)
            
            # Calculate confidence metrics
            avg_confidence = np.mean([s.confidence for s in self.signal_history])
            min_confidence = np.min([s.confidence for s in self.signal_history])
            max_confidence = np.max([s.confidence for s in self.signal_history])
            
            # Calculate signal balance
            signal_balance = abs(buy_signals - sell_signals)
            
            metrics = {
                'total_signals': total_signals,
                'buy_signals': buy_signals,
                'sell_signals': sell_signals,
                'signal_balance': signal_balance,
                'avg_confidence': avg_confidence,
                'min_confidence': min_confidence,
                'max_confidence': max_confidence,
                'strategy_name': self.name,
                'strategy_description': self.description
            }
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating performance metrics: {e}")
            return {}
    
    def update_parameters(self, new_params: Dict[str, Any]) -> None:
        """
        Update strategy parameters.
        
        Args:
            new_params: Dictionary with new parameters
        """
        try:
            for key, value in new_params.items():
                if hasattr(self, key):
                    setattr(self, key, value)
                    logger.info(f"Updated parameter {key} = {value}")
                else:
                    logger.warning(f"Unknown parameter: {key}")
                    
        except Exception as e:
            logger.error(f"Error updating parameters: {e}")
    
    def reset(self) -> None:
        """Reset strategy state."""
        try:
            self.signal_history = []
            self.total_signals = 0
            self.buy_signals = 0
            self.sell_signals = 0
            self.winning_signals = 0
            self.losing_signals = 0
            self.performance_metrics = {}
            
            logger.info(f"Reset {self.name}")
            
        except Exception as e:
            logger.error(f"Error resetting strategy: {e}")
    
    def get_signal_summary(self) -> str:
        """
        Get signal summary string.
        
        Returns:
            Formatted string with signal summary
        """
        try:
            metrics = self.get_performance_metrics()
            if not metrics:
                return "No signals generated"
            
            summary = f"""
Strategy: {self.name}
Total Signals: {metrics['total_signals']}
Buy Signals: {metrics['buy_signals']}
Sell Signals: {metrics['sell_signals']}
Signal Balance: {metrics['signal_balance']}
Average Confidence: {metrics['avg_confidence']:.2f}
            """
            
            return summary.strip()
            
        except Exception as e:
            logger.error(f"Error generating signal summary: {e}")
            return "Error generating summary"
    
    def __str__(self) -> str:
        """String representation of strategy."""
        return f"{self.name}: {self.description}"
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return f"BaseStrategy(name='{self.name}', signals={len(self.signal_history)})"
    
    def _convert_signals_to_list(self, signals: pd.Series, data: pd.DataFrame) -> List[Signal]:
        """
        Convert pandas Series signals to list of Signal objects.
        
        Args:
            signals: Pandas Series with signal values
            data: Market data DataFrame
            
        Returns:
            List of Signal objects
        """
        signal_list = []
        
        try:
            for i, signal_value in enumerate(signals):
                if signal_value != 0:  # Only non-zero signals
                    signal_type = SignalType(signal_value)
                    price = data['close'].iloc[i] if 'close' in data.columns else 0.0
                    timestamp = data.index[i] if hasattr(data.index[i], 'to_pydatetime') else datetime.now()
                    
                    if hasattr(timestamp, 'to_pydatetime'):
                        timestamp = timestamp.to_pydatetime()
                    
                    signal_obj = Signal(
                        timestamp=timestamp,
                        signal_type=signal_type,
                        price=price,
                        confidence=0.8,  # Default confidence
                        metadata={'strategy': self.name.lower().replace(' ', '_')}
                    )
                    signal_list.append(signal_obj)
            
            return signal_list
            
        except Exception as e:
            logger.error(f"Error converting signals to list: {e}")
            return []
    
    def _calculate_technical_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate common technical indicators.
        
        Args:
            data: Market data DataFrame
            
        Returns:
            DataFrame with technical indicators
        """
        try:
            # Simple Moving Averages
            data['sma_20'] = data['close'].rolling(window=20).mean()
            data['sma_50'] = data['close'].rolling(window=50).mean()
            
            # Exponential Moving Averages
            data['ema_12'] = data['close'].ewm(span=12).mean()
            data['ema_26'] = data['close'].ewm(span=26).mean()
            
            # RSI
            delta = data['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            data['rsi'] = 100 - (100 / (1 + rs))
            
            # MACD
            data['macd'] = data['ema_12'] - data['ema_26']
            data['macd_signal'] = data['macd'].ewm(span=9).mean()
            data['macd_histogram'] = data['macd'] - data['macd_signal']
            
            # Bollinger Bands
            data['bb_middle'] = data['close'].rolling(window=20).mean()
            bb_std = data['close'].rolling(window=20).std()
            data['bb_upper'] = data['bb_middle'] + (bb_std * 2)
            data['bb_lower'] = data['bb_middle'] - (bb_std * 2)
            
            # ATR
            high_low = data['high'] - data['low']
            high_close = np.abs(data['high'] - data['close'].shift())
            low_close = np.abs(data['low'] - data['close'].shift())
            true_range = np.maximum(high_low, np.maximum(high_close, low_close))
            data['atr'] = true_range.rolling(window=14).mean()
            
            return data
            
        except Exception as e:
            logger.error(f"Error calculating technical indicators: {e}")
            return data
    
    def _filter_signals_by_confidence(self, signals: List[Signal], 
                                    min_confidence: float = None) -> List[Signal]:
        """
        Filter signals by confidence level.
        
        Args:
            signals: List of signals to filter
            min_confidence: Minimum confidence threshold
            
        Returns:
            Filtered list of signals
        """
        try:
            if min_confidence is None:
                min_confidence = self.min_confidence
            
            filtered_signals = [s for s in signals if s.confidence >= min_confidence]
            
            logger.info(f"Filtered {len(signals)} signals to {len(filtered_signals)} "
                       f"(min_confidence: {min_confidence})")
            
            return filtered_signals
            
        except Exception as e:
            logger.error(f"Error filtering signals: {e}")
            return signals
    
    def _get_signal_statistics(self) -> Dict[str, Any]:
        """
        Get signal statistics.
        
        Returns:
            Dictionary with signal statistics
        """
        try:
            if not self.signal_history:
                return {}
            
            # Calculate statistics
            total_signals = len(self.signal_history)
            buy_signals = sum(1 for s in self.signal_history if s.signal_type == SignalType.BUY)
            sell_signals = sum(1 for s in self.signal_history if s.signal_type == SignalType.SELL)
            
            # Confidence statistics
            confidences = [s.confidence for s in self.signal_history]
            avg_confidence = np.mean(confidences)
            std_confidence = np.std(confidences)
            
            # Price statistics
            prices = [s.price for s in self.signal_history]
            avg_price = np.mean(prices)
            min_price = np.min(prices)
            max_price = np.max(prices)
            
            stats = {
                'total_signals': total_signals,
                'buy_signals': buy_signals,
                'sell_signals': sell_signals,
                'buy_ratio': buy_signals / total_signals if total_signals > 0 else 0,
                'sell_ratio': sell_signals / total_signals if total_signals > 0 else 0,
                'avg_confidence': avg_confidence,
                'std_confidence': std_confidence,
                'avg_price': avg_price,
                'min_price': min_price,
                'max_price': max_price,
                'price_range': max_price - min_price
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error calculating signal statistics: {e}")
            return {}

"""
Strategy Manager Module
======================
Professional strategy management system for TradingBot.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
import importlib
import os
import inspect
from datetime import datetime
from engine.logger import get_logger
from engine.config import create_config
from .strategies.base_strategy import BaseStrategy

# Initialize logger after config is created
logger = None

class StrategyManager:
    """
    Professional strategy management system.
    
    Features:
    - Dynamic strategy loading
    - Performance tracking
    - Risk management
    - Signal combination
    - Strategy optimization
    """
    
    def __init__(self, config: Dict[str, Any], enabled_strategies: Optional[Dict[str, bool]] = None):
        """
        Initialize strategy manager.
        
        Args:
            config: Configuration dictionary
            enabled_strategies: Dictionary of enabled strategies
        """
        self.config = config
        
        # Initialize logger
        global logger
        if logger is None:
            logger = get_logger("strategy_manager", config.get("BASE_DIR", ""))
        
        self.strategies: Dict[str, BaseStrategy] = {}
        self.signal_weights: Dict[str, float] = {}
        self.enabled_strategies = enabled_strategies or {}
        self.performance_history: List[Dict[str, Any]] = []
        
        # Strategy statistics
        self.total_signals_generated = 0
        self.last_optimization = None
        
        # Initialize strategies
        self._initialize_strategies()
        
        logger.info(f"StrategyManager initialized with {len(self.strategies)} strategies")
    
    def _initialize_strategies(self) -> None:
        """Initialize and load all available strategies."""
        strategies_dir = os.path.join(os.path.dirname(__file__), 'strategies')
        
        if not os.path.exists(strategies_dir):
            logger.error(f"Strategies directory not found: {strategies_dir}")
            return
        
        # Get strategy timeframe restrictions
        strategy_timeframes = self.config.get('strategy_timeframes', {})
        logger.info(f"Strategy timeframe restrictions: {strategy_timeframes}")
        
        # Load strategies
        for filename in os.listdir(strategies_dir):
            if not self._should_load_strategy_file(filename):
                continue
                
            try:
                self._load_strategy_from_file(filename, strategy_timeframes)
            except Exception as e:
                logger.error(f"[ERROR] Failed to load strategy from {filename}: {e}")
        
        logger.info(f"Loaded {len(self.strategies)} strategies: {list(self.strategies.keys())}")
    
    def _should_load_strategy_file(self, filename: str) -> bool:
        """Check if strategy file should be loaded."""
        if not (filename.endswith('.py') and 
                filename != 'base_strategy.py' and 
                not filename.startswith('__') and
                not filename.startswith('test_')):
            return False
        
        # Convert filename to strategy name (remove .py extension and underscores)
        filename_strategy_name = filename[:-3].lower().replace('_', '')
        
        # If no enabled_strategies dict provided, load all strategies
        if not self.enabled_strategies:
            return True
        
        # Check if any enabled strategy matches this filename
        # We need to check both the filename-based name and the class-based name
        should_load = False
        
        # First check filename-based name
        if filename_strategy_name in self.enabled_strategies:
            if self.enabled_strategies.get(filename_strategy_name, False):
                should_load = True
                logger.debug(f"Loading enabled strategy by filename: {filename_strategy_name} (from {filename})")
            else:
                logger.debug(f"Skipping disabled strategy by filename: {filename_strategy_name} (from {filename})")
                return False
        
        # If not found by filename, check if any enabled strategy would match the class name
        if not should_load:
            # Try to predict the class name from filename
            # Convert filename to class name: price_action_strategy.py -> PriceActionStrategy
            base_name = filename[:-3]  # Remove .py
            # Remove '_strategy' suffix if present
            if base_name.endswith('_strategy'):
                base_name = base_name[:-9]  # Remove '_strategy'
            class_name = ''.join(word.capitalize() for word in base_name.split('_')) + 'Strategy'
            predicted_strategy_key = class_name.replace('Strategy', '').lower()
            
            if predicted_strategy_key in self.enabled_strategies:
                if self.enabled_strategies.get(predicted_strategy_key, False):
                    should_load = True
                    logger.debug(f"Loading enabled strategy by class prediction: {predicted_strategy_key} (from {filename})")
                else:
                    logger.debug(f"Skipping disabled strategy by class prediction: {predicted_strategy_key} (from {filename})")
                    return False
        
        # If still not found, skip it
        if not should_load:
            logger.debug(f"Skipping strategy not in enabled list: {filename_strategy_name} (from {filename})")
            return False
        
        return True
    
    def _load_strategy_from_file(self, filename: str, strategy_timeframes: Dict[str, List[str]]) -> None:
        """Load strategy from a specific file."""
        module_name = f"engine.strategies.{filename[:-3]}"
        
        try:
            module = importlib.import_module(module_name)
            
            # Find strategy classes
            strategy_classes = self._find_strategy_classes(module, module_name)
            
            for class_name, strategy_class in strategy_classes:
                strategy_key = self._get_strategy_key(class_name)
                
                # Check if strategy is enabled
                if not self._is_strategy_enabled(strategy_key):
                    logger.info(f"Skipped disabled strategy: {class_name}")
                    continue
                
                # Create strategy instance
                strategy_instance = strategy_class(self.config)
                
                # Apply timeframe restrictions
                if strategy_key in strategy_timeframes:
                    self._apply_timeframe_restrictions(strategy_instance, strategy_key, strategy_timeframes[strategy_key])
                
                # Store strategy
                self.strategies[strategy_key] = strategy_instance
                self.signal_weights[strategy_key] = getattr(strategy_instance, 'signal_weight', 1.0)
                
                print(f"Loaded strategy: {class_name} -> {strategy_key}")
                logger.info(f"Loaded strategy: {class_name} -> {strategy_key}")
                
        except Exception as e:
            print(f"Error loading strategy from {filename}: {e}")
            logger.error(f"Error loading strategy from {filename}: {e}")
    
    def _find_strategy_classes(self, module: Any, module_name: str) -> List[Tuple[str, type]]:
        """Find strategy classes in a module."""
        strategy_classes = []
        
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (name.endswith('Strategy') and 
                name != 'BaseStrategy' and 
                obj.__module__ == module_name and
                issubclass(obj, BaseStrategy)):
                strategy_classes.append((name, obj))
        
        return strategy_classes
    
    def _get_strategy_key(self, class_name: str) -> str:
        """Get strategy key from class name."""
        return class_name.replace('Strategy', '').lower()
    
    def _is_strategy_enabled(self, strategy_key: str) -> bool:
        """Check if strategy is enabled."""
        if not self.enabled_strategies:
            return True
        return self.enabled_strategies.get(strategy_key, True)
    
    def _apply_timeframe_restrictions(self, strategy: BaseStrategy, strategy_key: str, 
                                    allowed_timeframes: List[str]) -> None:
        """Apply timeframe restrictions to strategy."""
        logger.info(f"📅 Strategy {strategy_key} restricted to: {allowed_timeframes}")
        
        # Store allowed timeframes in strategy instance
        strategy.allowed_timeframes = allowed_timeframes
        
        # Override generate_signals method to check timeframes
        original_generate_signals = strategy.generate_signals
        
        def restricted_generate_signals(data: pd.DataFrame, symbol: str = None, 
                                     timeframe: str = None, return_trades: bool = False) -> pd.Series:
            """Generate signals with timeframe restrictions."""
            if timeframe and timeframe not in allowed_timeframes:
                logger.debug(f"🚫 {strategy_key} disabled for {timeframe}. Allowed: {allowed_timeframes}")
                if return_trades:
                    return pd.DataFrame(columns=['entry_time', 'exit_time', 'entry_price', 
                                               'exit_price', 'signal', 'direction', 'size', 'profit'])
                return []
            
            return original_generate_signals(data, symbol, timeframe, return_trades)
        
        strategy.generate_signals = restricted_generate_signals
    
    def generate_combined_signals(self, data: pd.DataFrame, symbol: str = None, 
                                timeframe: str = None) -> Tuple[pd.Series, Dict[str, Any]]:
        """
        Generate combined signals from all active strategies.
        
        Args:
            data: Market data
            symbol: Trading symbol
            timeframe: Trading timeframe
            
        Returns:
            Tuple of (combined_signals, strategy_info)
        """
        if data.empty:
            return pd.Series(0, index=data.index), {}
        
        print(f"Generating combined signals for {symbol}:{timeframe}")
        logger.info(f"Generating combined signals for {symbol}:{timeframe}")
        
        try:
            strategy_signals = {}
            strategy_info = {}
            combined_signals = pd.Series(0, index=data.index)
            
            # Generate signals from each strategy
            for strategy_name, strategy in self.strategies.items():
                # Skip only if explicitly disabled
                if hasattr(strategy, 'is_active') and strategy.is_active == False:
                    continue
                
                try:
                    print(f"Generating signals for {strategy_name}...")
                    signals = strategy.generate_signals(data, symbol, timeframe)
                    print(f"{strategy_name}: Generated {len(signals) if signals else 0} signals")

                    last_meta: dict = {}
                    # Convert List[Signal] to pd.Series if needed
                    if isinstance(signals, list) and len(signals) > 0:
                        # Convert Signal objects to pandas Series
                        signal_series = pd.Series(0, index=data.index)
                        for signal in signals:
                            if hasattr(signal, "metadata") and signal.metadata:
                                last_meta = dict(signal.metadata)
                                if hasattr(signal, "confidence"):
                                    last_meta.setdefault(
                                        "confidence", float(signal.confidence)
                                    )
                            if hasattr(signal, 'signal_type'):
                                # For PriceActionSignal, use the signal_type directly
                                signal_value = signal.signal_type.value if hasattr(signal.signal_type, 'value') else signal.signal_type
                                
                                if hasattr(signal, 'timestamp'):
                                    # Find the closest timestamp in data - fixed version
                                    try:
                                        time_diff = abs(data.index - signal.timestamp)
                                        # Use numpy argmin for reliable indexing
                                        min_idx = np.argmin(time_diff)
                                        closest_idx = data.index[min_idx]
                                        
                                        # Check if timestamp is close enough (within 5 minutes)
                                        if time_diff[min_idx] < pd.Timedelta(minutes=5):
                                            # Use iloc for safer indexing
                                            signal_series.iloc[min_idx] = signal_value
                                    except Exception as e:
                                        logger.warning(f"Error processing signal timestamp: {e}")
                                        # Fallback: place signal at first available position
                                        for i in range(len(signal_series)):
                                            if signal_series.iloc[i] == 0:
                                                signal_series.iloc[i] = signal_value
                                                break
                                else:
                                    # If no timestamp, place signals sequentially
                                    for i in range(len(signal_series)):
                                        if signal_series.iloc[i] == 0:
                                            signal_series.iloc[i] = signal_value
                                            break
                            else:
                                # Handle simple signal values
                                pass
                        
                        signals = signal_series
                        
                    elif isinstance(signals, list) and len(signals) == 0:
                        signals = pd.Series(0, index=data.index)  # Empty series
                    
                    elif isinstance(signals, pd.Series):
                        pass  # Already correct format
                    
                    else:
                        signals = pd.Series(0, index=data.index)  # Default to empty
                    
                    # Ensure signals is a pandas Series
                    if isinstance(signals, list):
                        signals = pd.Series(0, index=data.index)
                    
                    if not signals.empty and (signals != 0).any():
                        strategy_signals[strategy_name] = signals
                    strategy_info[strategy_name] = {
                        'signals_count': (signals != 0).sum(),
                        'last_signal': signals[signals != 0].iloc[-1] if (signals != 0).any() else 0,
                        'performance': strategy.get_performance_metrics(),
                        'metadata': last_meta,
                    }
                    
                    # Combine signals with weights - اصلاح منطق ترکیب
                    weight = self.signal_weights.get(strategy_name, 1.0)
                    
                    # ترکیب صحیح سیگنال‌ها - Buy و Sell جداگانه
                    try:
                        combined_signals += signals * weight
                    except Exception as e:
                        logger.error(f"Error combining signals for {strategy_name}: {e}")
                        continue
                    
                    logger.debug(f"{strategy_name}: {signals[signals != 0].sum()} signals")
                    
                except Exception as e:
                    logger.error(f"Error in {strategy_name}: {e}")
                    continue
            
            # Normalize combined signals
            combined_signals = self._normalize_signals(combined_signals)
            
            # Update statistics
            self.total_signals_generated += 1
            
            logger.info(f"[SUCCESS] Generated combined signals: {combined_signals[combined_signals != 0].sum()} total")
            
            return combined_signals, strategy_info
            
        except Exception as e:
            logger.error(f"[ERROR] Error generating combined signals: {e}")
            return pd.Series(0, index=data.index), {}
    
    def _normalize_signals(self, signals: pd.Series) -> pd.Series:
        """Normalize combined signals to [-1, 0, 1] range."""
        if signals.empty:
            return signals
        
        # Apply threshold-based normalization - VERY RELAXED for backtesting
        threshold = 0.001  # VERY VERY LOW threshold - Accept almost any signal for backtesting
        normalized = pd.Series(0, index=signals.index)
        
        # Use .loc for proper boolean indexing - اصلاح مشکل Series
        buy_mask = signals > threshold
        sell_mask = signals < -threshold
        
        if buy_mask.any():
            normalized.loc[buy_mask] = 1
        if sell_mask.any():
            normalized.loc[sell_mask] = -1
        
        # Debug: Log signal values before normalization
        if not signals.empty:
            max_signal = signals.max()
            min_signal = signals.min()
            buy_count = (normalized == 1).sum()
            sell_count = (normalized == -1).sum()
            logger.info(f"[DEBUG] Signal range: min={min_signal:.4f}, max={max_signal:.4f}, threshold={threshold}, Buy={buy_count}, Sell={sell_count}")
            print(f"[DEBUG] Signal range: min={min_signal:.4f}, max={max_signal:.4f}, threshold={threshold}, Buy={buy_count}, Sell={sell_count}")
        
        # Log signal distribution for debugging
        buy_count = (normalized == 1).sum()
        sell_count = (normalized == -1).sum()
        if buy_count > 0 or sell_count > 0:
            logger.info(f"Signal distribution: Buy={buy_count}, Sell={sell_count}, Total={buy_count + sell_count}")
        
        return normalized
    
    def get_strategy_performance(self, strategy_name: str = None) -> Dict[str, Any]:
        """Get performance metrics for strategies."""
        if strategy_name:
            if strategy_name in self.strategies:
                return self.strategies[strategy_name].get_performance_metrics()
            return {}
        
        # Aggregate performance for all strategies
        total_signals = 0
        total_wins = 0
        total_profit = 0.0
        
        for strategy in self.strategies.values():
            metrics = strategy.get_performance_metrics()
            total_signals += metrics.get('total_signals', 0)
            total_wins += metrics.get('winning_signals', 0)
            total_profit += metrics.get('total_profit', 0.0)
        
        overall_win_rate = (total_wins / total_signals * 100) if total_signals > 0 else 0
        
        return {
            'total_strategies': len(self.strategies),
            'active_strategies': sum(1 for s in self.strategies.values() if s.is_active),
            'total_signals': total_signals,
            'total_wins': total_wins,
            'overall_win_rate': overall_win_rate,
            'total_profit': total_profit
        }
    
    def optimize_strategies(self) -> Dict[str, Any]:
        """Optimize strategy parameters based on performance."""
        logger.info("[TOOL] Starting strategy optimization...")
        
        optimization_results = {}
        
        for strategy_name, strategy in self.strategies.items():
            try:
                if hasattr(strategy, 'optimize_parameters'):
                    result = strategy.optimize_parameters()
                    optimization_results[strategy_name] = result
                    logger.info(f"[SUCCESS] Optimized {strategy_name}")
                else:
                    logger.debug(f"[PAUSED] {strategy_name} has no optimization method")
                    
            except Exception as e:
                logger.error(f"[ERROR] Error optimizing {strategy_name}: {e}")
                optimization_results[strategy_name] = {'error': str(e)}
        
        self.last_optimization = datetime.now()
        logger.info(f"[SUCCESS] Strategy optimization completed for {len(optimization_results)} strategies")
        
        return optimization_results
    
    def enable_strategy(self, strategy_name: str) -> bool:
        """Enable a specific strategy."""
        if strategy_name in self.strategies:
            self.strategies[strategy_name].enable()
            logger.info(f"[SUCCESS] Enabled strategy: {strategy_name}")
            return True
        else:
            logger.warning(f"[WARNING] Strategy not found: {strategy_name}")
            return False
    
    def disable_strategy(self, strategy_name: str) -> bool:
        """Disable a specific strategy."""
        if strategy_name in self.strategies:
            self.strategies[strategy_name].disable()
            logger.info(f"[PAUSED] Disabled strategy: {strategy_name}")
            return True
        else:
            logger.warning(f"[WARNING] Strategy not found: {strategy_name}")
            return False
    
    def reset_strategies(self) -> None:
        """Reset all strategies."""
        for strategy in self.strategies.values():
                strategy.reset()
        
        self.total_signals_generated = 0
        self.last_optimization = None
        
        logger.info("[REFRESH] All strategies reset")
    
    def get_strategy_status(self) -> Dict[str, str]:
        """Get status of all strategies."""
        return {name: strategy.get_status() for name, strategy in self.strategies.items()}
    
    def __str__(self) -> str:
        """String representation of strategy manager."""
        performance = self.get_strategy_performance()
        return (f"StrategyManager: {performance['active_strategies']}/{performance['total_strategies']} "
                f"active, {performance['overall_win_rate']:.1f}% WR")
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return f"StrategyManager(strategies={list(self.strategies.keys())}, enabled={self.enabled_strategies})" 
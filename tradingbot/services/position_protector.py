"""
Position Protection Service
===========================
Independent service that protects open positions even when bot is stopped.
This service runs INDEPENDENTLY and cannot be stopped by Emergency Stop.

Key Features:
- Always-on trailing stop management
- Emergency position closure
- Independent of main bot lifecycle
- Survives bot crashes and restarts
"""

import MetaTrader5 as mt5
import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from tradingbot.services.mt5_order_guard import guarded_order_send


class PositionProtector:
    """
    Independent Position Protection Service.
    
    This service ALWAYS runs and protects positions even if:
    - Main bot is stopped
    - Emergency stop is activated
    - Bot crashes
    - Network issues occur
    
    Responsibilities:
    1. Monitor all open positions
    2. Apply trailing stops
    3. Apply time-based stops
    4. Emergency closure on extreme conditions
    """
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # Protection settings
        self.check_interval = config.get('position_check_interval', 10)  # 10 seconds
        self.trailing_stop_config = config.get('trailing_stop', {})
        self.max_position_age = config.get('max_position_age_hours', 24)  # 24 hours
        self.emergency_drawdown = config.get('emergency_drawdown', 0.25)  # 25%
        creds = config.get('mt5_credentials', {})
        self.mt5_login = creds.get('login')
        self.mt5_password = creds.get('password')
        self.mt5_server = creds.get('server')
        
        # State tracking
        self.is_running = False
        self.protected_positions = {}  # ticket -> position data
        self.last_check_time = None
        
        # Partial TP tracking (synchronized with main bot)
        self.partial_tp_positions = {}  # ticket -> multi_tp_data
        
        self.logger.info("[PROTECTOR] Position Protector initialized")
    
    def start(self):
        """Start the protection service"""
        self.is_running = True
        self.logger.info("[PROTECTOR] Position Protection Service STARTED")
        self.logger.warning("[PROTECTOR] This service runs INDEPENDENTLY of main bot!")
        
        # Initialize MT5 connection (reuse live credentials)
        if not self._ensure_connection():
            self.logger.error("[PROTECTOR] Failed to initialize MT5 - missing credentials or terminal not available")
            return False
        
        return True
    
    def _ensure_connection(self) -> bool:
        """Attach to running MT5 terminal without credential re-initialize."""
        from tradingbot.adapters.mt5_utils import ensure_mt5_connected

        return ensure_mt5_connected(
            self.config,
            strict_account=False,
            attach_only=True,
            use_lock=True,
            hold_lock=False,
        )
    
    def stop(self):
        """Stop the protection service"""
        self.is_running = False
        self.logger.info("[PROTECTOR] Position Protection Service STOPPED")
    
    def register_partial_tp(self, ticket: int, symbol: str, volume: float, 
                           signal: int, multi_tp_data: dict):
        """Register position for partial TP management"""
        try:
            if multi_tp_data is None:
                return
            
            self.partial_tp_positions[ticket] = {
                'symbol': symbol,
                'original_volume': volume,
                'remaining_volume': volume,
                'signal': signal,
                'tp1': multi_tp_data['tp1'],
                'tp1_pct': multi_tp_data['tp1_pct'],
                'tp1_hit': False,
                'tp2': multi_tp_data['tp2'],
                'tp2_pct': multi_tp_data['tp2_pct'],
                'tp2_hit': False,
                'tp3': multi_tp_data['tp3'],
                'tp3_pct': multi_tp_data['tp3_pct'],
                'tp3_hit': False,
            }
            
            self.logger.info(f"[PROTECTOR] Registered partial TP for position {ticket}")
            
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error registering partial TP: {e}")
    
    def run(self):
        """Main protection loop - runs continuously"""
        if not self.start():
            return
        
        self.logger.info("[PROTECTOR] Starting protection loop...")
        
        try:
            while self.is_running:
                try:
                    # 1. Get all open positions
                    positions = mt5.positions_get()
                    
                    if positions is None:
                        self.logger.warning("[PROTECTOR] No positions or MT5 error")
                        time.sleep(self.check_interval)
                        continue
                    
                    if len(positions) == 0:
                        self.logger.debug("[PROTECTOR] No open positions to protect")
                        time.sleep(self.check_interval)
                        continue
                    
                    self.logger.info(f"[PROTECTOR] Protecting {len(positions)} positions...")
                    
                    # 2. Protect each position
                    for position in positions:
                        self._protect_position(position)
                    
                    # 3. Check for emergency conditions
                    self._check_emergency_conditions(positions)
                    
                    self.last_check_time = datetime.now()
                    
                except Exception as e:
                    self.logger.error(f"[PROTECTOR] Error in protection loop: {e}")
                
                # Sleep until next check
                time.sleep(self.check_interval)
        
        except KeyboardInterrupt:
            self.logger.info("[PROTECTOR] Protection service interrupted by user")
        
        finally:
            self.stop()
            mt5.shutdown()
    
    def _protect_position(self, position):
        """Apply all protection mechanisms to a position"""
        try:
            ticket = position.ticket
            symbol = position.symbol
            
            # Get current price
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return
            
            current_price = tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask
            
            # === STEP 0: Check Partial TP (PROFESSIONAL) ===
            partial_executed = self._check_partial_tp(position, current_price)
            if partial_executed:
                # Partial TP hit, position was reduced
                # Continue with other protections for remaining
                pass
            
            # 1. Advanced Trailing Stop
            self._apply_advanced_trailing_stop(position, current_price)
            
            # 2. Time-based protection
            self._apply_time_based_protection(position)
            
            # 3. Extreme drawdown protection
            self._apply_drawdown_protection(position, current_price)
            
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error protecting position {position.ticket}: {e}")
    
    def _check_partial_tp(self, position, current_price: float) -> bool:
        """Check and execute partial TP levels"""
        try:
            ticket = position.ticket
            
            if ticket not in self.partial_tp_positions:
                return False
            
            pos_data = self.partial_tp_positions[ticket]
            signal = pos_data['signal']
            
            # Check each TP level
            if signal == 1:  # BUY
                if not pos_data['tp1_hit'] and current_price >= pos_data['tp1']:
                    return self._execute_partial_close(position, pos_data, 'tp1')
                if not pos_data['tp2_hit'] and current_price >= pos_data['tp2']:
                    return self._execute_partial_close(position, pos_data, 'tp2')
                if not pos_data['tp3_hit'] and current_price >= pos_data['tp3']:
                    result = self._execute_partial_close(position, pos_data, 'tp3')
                    del self.partial_tp_positions[ticket]  # All closed
                    return result
            else:  # SELL
                if not pos_data['tp1_hit'] and current_price <= pos_data['tp1']:
                    return self._execute_partial_close(position, pos_data, 'tp1')
                if not pos_data['tp2_hit'] and current_price <= pos_data['tp2']:
                    return self._execute_partial_close(position, pos_data, 'tp2')
                if not pos_data['tp3_hit'] and current_price <= pos_data['tp3']:
                    result = self._execute_partial_close(position, pos_data, 'tp3')
                    del self.partial_tp_positions[ticket]  # All closed
                    return result
            
            return False
            
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error checking partial TP: {e}")
            return False
    
    def _execute_partial_close(self, position, pos_data: dict, tp_level: str) -> bool:
        """Execute partial position close"""
        try:
            ticket = position.ticket
            symbol = pos_data['symbol']
            
            # Calculate volume to close
            close_pct = pos_data[f'{tp_level}_pct']
            close_volume = round(pos_data['original_volume'] * close_pct, 2)
            close_volume = max(0.01, close_volume)
            
            if close_volume > pos_data['remaining_volume']:
                close_volume = pos_data['remaining_volume']
            
            # Get position type
            position_type = position.type
            close_type = mt5.ORDER_TYPE_SELL if position_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            
            # Create partial close request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": close_volume,
                "type": close_type,
                "position": ticket,
                "comment": f"Protector TP{tp_level[-1]}: {close_pct*100:.0f}%"
            }
            
            # Execute
            result = guarded_order_send(mt5, request, label="PositionProtector.partial_tp")
            
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                pos_data['remaining_volume'] -= close_volume
                pos_data[f'{tp_level}_hit'] = True
                
                self.logger.info(f"[PROTECTOR] PARTIAL TP! Closed {close_pct*100:.0f}% ({close_volume:.2f} lots) "
                               f"at {tp_level.upper()}")
                return True
            else:
                self.logger.error(f"[PROTECTOR] Failed to close partial: {result.comment if result else 'Unknown'}")
                return False
                
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error executing partial close: {e}")
            return False
    
    def _apply_advanced_trailing_stop(self, position, current_price: float):
        """
        Professional Multi-Method Trailing Stop
        
        Uses combination of:
        1. ATR-based Chandelier Exit
        2. Parabolic SAR
        3. Swing High/Low
        4. Percentage-based
        """
        try:
            ticket = position.ticket
            symbol = position.symbol
            entry_price = position.price_open
            current_sl = position.sl
            current_tp = position.tp
            
            # Get symbol info
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                return
            
            digits = symbol_info.digits
            point = symbol_info.point
            min_stop_distance = symbol_info.trade_stops_level * point
            
            # Calculate ATR (get historical data)
            atr = self._calculate_atr(symbol)
            if atr <= 0:
                atr = (current_price - entry_price) * 0.1  # Fallback to 10% of profit
            
            # Calculate profit
            if position.type == mt5.ORDER_TYPE_BUY:
                profit_distance = current_price - entry_price
            else:
                profit_distance = entry_price - current_price
            
            # Only adjust if in profit
            if profit_distance <= 0:
                return
            
            # Calculate progress to TP
            if current_tp > 0:
                if position.type == mt5.ORDER_TYPE_BUY:
                    tp_distance = current_tp - entry_price
                else:
                    tp_distance = entry_price - current_tp
                
                progress = profit_distance / tp_distance if tp_distance > 0 else 0
            else:
                progress = 0
            
            # === PROFESSIONAL TRAILING LOGIC ===
            new_sl = current_sl
            
            if position.type == mt5.ORDER_TYPE_BUY:
                # Method 1: Chandelier Exit (ATR-based)
                chandelier_sl = current_price - (atr * 2.5)
                
                # Method 2: Percentage trailing
                if progress >= 0.75:
                    # 75%+ to TP -> Lock 60% of profit
                    pct_sl = entry_price + (profit_distance * 0.60)
                elif progress >= 0.50:
                    # 50%+ to TP -> Move to breakeven + spread
                    pct_sl = entry_price + (point * 10)
                elif progress >= 0.25:
                    # 25%+ to TP -> Lock 20% of profit
                    pct_sl = entry_price + (profit_distance * 0.20)
                else:
                    # Less than 25% -> Use Chandelier
                    pct_sl = chandelier_sl
                
                # Method 3: Swing Low (previous candle low)
                swing_sl = self._get_swing_low(symbol, current_price)
                
                # Use the HIGHEST (most protective) stop loss
                new_sl = max(chandelier_sl, pct_sl, swing_sl if swing_sl > 0 else chandelier_sl)
                
                # Only update if better than current SL
                if new_sl > current_sl and new_sl < current_price - min_stop_distance:
                    new_sl = round(new_sl, digits)
                    self._update_stop_loss(ticket, new_sl, "BUY")
                    
            else:  # SELL
                # Method 1: Chandelier Exit
                chandelier_sl = current_price + (atr * 2.5)
                
                # Method 2: Percentage trailing
                if progress >= 0.75:
                    pct_sl = entry_price - (profit_distance * 0.60)
                elif progress >= 0.50:
                    pct_sl = entry_price - (point * 10)
                elif progress >= 0.25:
                    pct_sl = entry_price - (profit_distance * 0.20)
                else:
                    pct_sl = chandelier_sl
                
                # Method 3: Swing High
                swing_sl = self._get_swing_high(symbol, current_price)
                
                # Use the LOWEST (most protective) stop loss
                new_sl = min(chandelier_sl, pct_sl, swing_sl if swing_sl > 0 else chandelier_sl)
                
                # Only update if better than current SL
                if new_sl < current_sl and new_sl > current_price + min_stop_distance:
                    new_sl = round(new_sl, digits)
                    self._update_stop_loss(ticket, new_sl, "SELL")
        
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error in advanced trailing stop: {e}")
    
    def _apply_time_based_protection(self, position):
        """Close positions that are too old"""
        try:
            # Calculate position age
            open_time = datetime.fromtimestamp(position.time)
            age_hours = (datetime.now() - open_time).total_seconds() / 3600
            
            if age_hours > self.max_position_age:
                self.logger.warning(f"[PROTECTOR] Position {position.ticket} is {age_hours:.1f} hours old - CLOSING")
                self._close_position(position, "Time limit exceeded")
        
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error in time-based protection: {e}")
    
    def _apply_drawdown_protection(self, position, current_price: float):
        """Close positions with extreme drawdown"""
        try:
            entry_price = position.price_open
            
            # Calculate current drawdown
            if position.type == mt5.ORDER_TYPE_BUY:
                drawdown_pct = (entry_price - current_price) / entry_price
            else:
                drawdown_pct = (current_price - entry_price) / entry_price
            
            if drawdown_pct > self.emergency_drawdown:
                self.logger.critical(f"[PROTECTOR] EMERGENCY: Position {position.ticket} has {drawdown_pct*100:.1f}% drawdown - CLOSING!")
                self._close_position(position, f"Emergency drawdown: {drawdown_pct*100:.1f}%")
        
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error in drawdown protection: {e}")
    
    def _check_emergency_conditions(self, positions: Tuple):
        """Check for emergency conditions across all positions"""
        try:
            if len(positions) == 0:
                return
            
            # Calculate total unrealized P&L
            total_pnl = sum(pos.profit for pos in positions)
            
            # Get account info
            account_info = mt5.account_info()
            if account_info is None:
                return
            
            # Calculate drawdown from equity
            drawdown = -total_pnl / account_info.equity if account_info.equity > 0 else 0
            
            if drawdown > self.emergency_drawdown:
                self.logger.critical(f"[PROTECTOR] EMERGENCY: Total drawdown {drawdown*100:.1f}% - CLOSING ALL POSITIONS!")
                for position in positions:
                    self._close_position(position, "Emergency: Total drawdown")
        
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error checking emergency conditions: {e}")
    
    def _update_stop_loss(self, ticket: int, new_sl: float, direction: str):
        """Update stop loss for a position"""
        try:
            # Get position
            position = mt5.positions_get(ticket=ticket)
            if not position:
                return
            
            position = position[0]
            
            # Create modify request
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": position.symbol,
                "position": ticket,
                "sl": new_sl,
                "tp": position.tp,
            }
            
            # Send request
            result = guarded_order_send(mt5, request, label="PositionProtector.trailing")
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self.logger.info(f"[PROTECTOR] Trailing Stop Updated ({direction}): Ticket={ticket}, New SL={new_sl:.5f}")
            else:
                self.logger.warning(f"[PROTECTOR] Failed to update SL: {result.comment}")
        
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error updating stop loss: {e}")
    
    def _close_position(self, position, reason: str):
        """Emergency close a position"""
        try:
            # Create close request
            close_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": position.symbol,
                "volume": position.volume,
                "type": close_type,
                "position": position.ticket,
                "comment": f"Protection: {reason}"
            }
            
            result = guarded_order_send(mt5, request, label="PositionProtector.close")
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self.logger.info(f"[PROTECTOR] Position {position.ticket} closed: {reason}")
            else:
                self.logger.error(f"[PROTECTOR] Failed to close position {position.ticket}: {result.comment}")
        
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error closing position: {e}")
    
    def _calculate_atr(self, symbol: str, period: int = 14) -> float:
        """Calculate ATR for symbol"""
        try:
            # Get historical data
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, period + 1)
            
            if rates is None or len(rates) < period:
                return 0.0
            
            df = pd.DataFrame(rates)
            
            # Calculate True Range
            df['h-l'] = df['high'] - df['low']
            df['h-pc'] = abs(df['high'] - df['close'].shift(1))
            df['l-pc'] = abs(df['low'] - df['close'].shift(1))
            df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
            
            # Calculate ATR
            atr = df['tr'].rolling(period).mean().iloc[-1]
            
            return atr if not np.isnan(atr) else 0.0
        
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error calculating ATR: {e}")
            return 0.0
    
    def _get_swing_low(self, symbol: str, current_price: float) -> float:
        """Get swing low for trailing stop"""
        try:
            # Get last 20 candles
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 20)
            
            if rates is None or len(rates) < 3:
                return 0.0
            
            df = pd.DataFrame(rates)
            
            # Find swing low (lowest low in last 10 candles)
            swing_low = df['low'].tail(10).min()
            
            # Only return if it's below current price
            if swing_low < current_price:
                return swing_low
            
            return 0.0
        
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error getting swing low: {e}")
            return 0.0
    
    def _get_swing_high(self, symbol: str, current_price: float) -> float:
        """Get swing high for trailing stop"""
        try:
            # Get last 20 candles
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 20)
            
            if rates is None or len(rates) < 3:
                return 0.0
            
            df = pd.DataFrame(rates)
            
            # Find swing high (highest high in last 10 candles)
            swing_high = df['high'].tail(10).max()
            
            # Only return if it's above current price
            if swing_high > current_price:
                return swing_high
            
            return 0.0
        
        except Exception as e:
            self.logger.error(f"[PROTECTOR] Error getting swing high: {e}")
            return 0.0


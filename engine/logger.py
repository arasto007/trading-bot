"""
Professional Logging System
==========================
Advanced logging system with structured logging, rotation, and performance optimization.
"""

import logging
import os
import json
import time
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, Any, Optional, Union
import warnings

# Suppress warnings
warnings.filterwarnings('ignore')

# Custom log level for summary reports
SUMMARY = 25
logging.addLevelName(SUMMARY, "SUMMARY")

class ContextFilter(logging.Filter):
    """
    Add contextual information (symbol, timeframe) to logs.
    
    Features:
    - Symbol and timeframe context
    - Request ID tracking
    - Performance metrics
    """
    
    def __init__(self, symbol: str = None, timeframe: str = None, request_id: str = None):
        super().__init__()
        self.symbol = symbol or "-"
        self.timeframe = timeframe or "-"
        self.request_id = request_id or self._generate_request_id()

    def filter(self, record):
        record.symbol = self.symbol
        record.timeframe = self.timeframe
        record.request_id = self.request_id
        record.timestamp = datetime.now().isoformat()
        return True
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID."""
        return f"req_{int(time.time() * 1000)}_{os.getpid()}"

class RepetitiveMessageFilter(logging.Filter):
    """
    Filter out repetitive messages to reduce log noise.
    
    Features:
    - Message deduplication
    - Summary reporting
    - Configurable thresholds
    """
    
    def __init__(self, max_repeat: int = 100, summary_logger=None, 
                 level: int = logging.INFO, time_window: int = 3600):
        super().__init__()
        self.msg_count = defaultdict(int)
        self.msg_timestamps = defaultdict(list)
        self.max_repeat = max_repeat
        self.summary_logger = summary_logger
        self.level = level
        self.time_window = time_window
    
    def filter(self, record):
        msg = record.getMessage()
        current_time = time.time()
        
        # Clean old timestamps
        self.msg_timestamps[msg] = [
            ts for ts in self.msg_timestamps[msg] 
            if current_time - ts < self.time_window
        ]
        
        # Add current timestamp
        self.msg_timestamps[msg].append(current_time)
        count = len(self.msg_timestamps[msg])
        
        # Update message count
        self.msg_count[msg] = count
        
        # Log first occurrence and every max_repeat occurrence
        if count == 1 or count % self.max_repeat == 0:
            if count > 1 and self.summary_logger:
                self.summary_logger.log(
                    self.level, 
                    f"[SUMMARY] Message repeated {count} times in {self.time_window}s: {msg}"
                )
            return True
        
        return False

class JsonFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    
    Features:
    - Structured JSON output
    - Context information
    - Performance metrics
    - Error details
    """
    
    def __init__(self, include_context: bool = True, include_performance: bool = True):
        super().__init__()
        self.include_context = include_context
        self.include_performance = include_performance
    
    def format(self, record):
        log_record = {
            'timestamp': getattr(record, 'timestamp', datetime.now().isoformat()),
            'level': record.levelname,
            'module': record.name,
            'message': record.getMessage(),
            'logger_name': record.name,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add context information
        if self.include_context:
            log_record.update({
            'symbol': getattr(record, 'symbol', '-'),
            'timeframe': getattr(record, 'timeframe', '-'),
                'request_id': getattr(record, 'request_id', '-')
            })
        
        # Add performance information
        if self.include_performance and hasattr(record, 'performance'):
            log_record['performance'] = record.performance
        
        # Add exception information
        if record.exc_info:
            log_record['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': self.formatException(record.exc_info)
            }
        
        return json.dumps(log_record, ensure_ascii=False, default=str)

class SummaryFormatter(logging.Formatter):
    """Custom formatter for SUMMARY level logs."""
    
    def format(self, record):
        if record.levelno == SUMMARY:
            return f"[SUMMARY] {record.getMessage()}"
        return super().format(record)

class PerformanceLogger:
    """
    Performance logging utility.
    
    Features:
    - Function timing
    - Memory usage tracking
    - Performance metrics
    """
    
    def __init__(self, logger, operation_name: str):
        self.logger = logger
        self.operation_name = operation_name
        self.start_time = time.time()
        self.start_memory = self._get_memory_usage()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_time = time.time() - self.start_time
        end_memory = self._get_memory_usage()
        memory_diff = end_memory - self.start_memory
        
        performance_info = {
            'operation': self.operation_name,
            'elapsed_time_ms': round(elapsed_time * 1000, 2),
            'memory_diff_mb': round(memory_diff / 1024 / 1024, 2)
        }
        
        if exc_type:
            self.logger.error(f"[FAILED] Operation failed: {self.operation_name}", 
                             extra={'performance': performance_info})
        else:
            self.logger.debug(f"[COMPLETED] Operation completed: {self.operation_name}", 
                             extra={'performance': performance_info})
    
    def _get_memory_usage(self) -> int:
        """Get current memory usage in bytes."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss
        except ImportError:
            return 0

def get_log_path(base_dir: str, module: str, symbol: str = None, 
                 timeframe: str = None, level: str = 'all') -> str:
    """
    Generate log file path with proper directory structure.
    
    Args:
        base_dir: Base directory for logs
        module: Module name
        symbol: Trading symbol
        timeframe: Trading timeframe
        level: Log level
        
    Returns:
        Full log file path
    """
    try:
        # Create log directory
        log_dir = os.path.join(base_dir, "logs", module)
        os.makedirs(log_dir, exist_ok=True)
        
        # Clean up symbol and timeframe names for file naming
        symbol_clean = (symbol or 'all').replace(':', '_').replace('/', '_').replace('\\', '_')
        timeframe_clean = (timeframe or 'all').replace(':', '_').replace('/', '_').replace('\\', '_')
        
        # Generate filename
        filename = f"{symbol_clean}_{timeframe_clean}_{level}.log"
        return os.path.join(log_dir, filename)
        
    except Exception as e:
        # Fallback to simple naming if there's an error
        fallback_path = os.path.join(base_dir, "logs", f"{module}_{level}.log")
        print(f"Warning: Could not generate log path, using fallback: {fallback_path}")
        return fallback_path

def setup_logger(base_dir: str, module: str, symbol: str = None, 
                timeframe: str = None, level: str = 'INFO', 
                config: Dict[str, Any] = None) -> logging.Logger:
    """
    Setup logger with proper configuration.
    
    Args:
        base_dir: Base directory for logs
        module: Module name
        symbol: Trading symbol
        timeframe: Trading timeframe
        level: Log level
        config: Configuration dictionary
        
    Returns:
        Configured logger instance
    """
    try:
        # Get configuration
        if config is None:
            try:
                from engine.config import config as global_config
                config = global_config
            except ImportError:
                config = {}
        
        # Logger name
        logger_name = f"TradingBot.{module}"
        if symbol:
            logger_name += f".{symbol}"
        if timeframe:
            logger_name += f".{timeframe}"
        
        # Check if logger already exists
        if logger_name in logging.root.manager.loggerDict:
            return logging.getLogger(logger_name)
        
        # Create logger
        logger = logging.getLogger(logger_name)
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        
        # Prevent duplicate handlers
        if logger.handlers:
            return logger
            
        # Create handlers
        handlers = []
        
        # Console handler
        if hasattr(config, 'get') and config.get('console_logging', True):
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(console_formatter)
            # Set encoding to UTF-8 for Windows compatibility
            try:
                import sys
                if hasattr(sys.stdout, 'reconfigure'):
                    sys.stdout.reconfigure(encoding='utf-8')
                if hasattr(sys.stderr, 'reconfigure'):
                    sys.stderr.reconfigure(encoding='utf-8')
            except:
                pass
            handlers.append(console_handler)
        
        # File handlers for different levels
        log_levels = ['debug', 'info', 'warning', 'error', 'critical']
        
        for log_level in log_levels:
            if hasattr(config, 'get') and config.get(f'{log_level}_logging', True):
                file_path = get_log_path(base_dir, module, symbol, timeframe, log_level)
                
                # Create rotating file handler
                file_handler = RotatingFileHandler(
                    file_path,
                    maxBytes=config.get('max_log_size', 10 * 1024 * 1024) if hasattr(config, 'get') else 10 * 1024 * 1024,  # 10MB
                    backupCount=config.get('max_log_backups', 5) if hasattr(config, 'get') else 5
                )
                
                file_handler.setLevel(getattr(logging, log_level.upper()))
                
                # Set formatter based on level
                if log_level == 'debug':
                    formatter = JsonFormatter(include_context=True, include_performance=True)
                else:
                    formatter = JsonFormatter(include_context=True, include_performance=False)
                
                file_handler.setFormatter(formatter)
                handlers.append(file_handler)
        
        # Add handlers to logger
        for handler in handlers:
            logger.addHandler(handler)

        # Add context filter
        context_filter = ContextFilter(symbol, timeframe)
        logger.addFilter(context_filter)
        
        # Add repetitive message filter
        if hasattr(config, 'get') and config.get('filter_repetitive', True):
            repetitive_filter = RepetitiveMessageFilter(
                max_repeat=config.get('max_message_repeat', 100) if hasattr(config, 'get') else 100,
                time_window=config.get('message_time_window', 3600) if hasattr(config, 'get') else 3600
            )
            logger.addFilter(repetitive_filter)
        
        # Prevent propagation to root logger
        logger.propagate = False

        return logger
        
    except Exception as e:
        # Fallback logger
        fallback_logger = logging.getLogger(f"TradingBot.{module}.fallback")
        fallback_logger.setLevel(logging.INFO)
        
        if not fallback_logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            fallback_logger.addHandler(handler)
        
        fallback_logger.error(f"Failed to setup logger: {e}")
        return fallback_logger

def get_logger(module: str, base_dir: str = ".", symbol: str = None, 
               timeframe: str = None, config: Dict[str, Any] = None) -> logging.Logger:
    """
    Get logger instance for the specified module.
    
    Args:
        module: Module name
        base_dir: Base directory for logs
        symbol: Trading symbol
        timeframe: Trading timeframe
        config: Configuration dictionary
        
    Returns:
        Logger instance
    """
    try:
        return setup_logger(base_dir, module, symbol, timeframe, 'INFO', config)
    except Exception as e:
        # Return basic logger if setup fails
        basic_logger = logging.getLogger(f"TradingBot.{module}")
        basic_logger.setLevel(logging.INFO)
        
        if not basic_logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            basic_logger.addHandler(handler)
        
        basic_logger.error(f"Logger setup failed: {e}")
        return basic_logger

def log_performance(logger: logging.Logger, operation_name: str):
    """
    Decorator for logging function performance.
    
    Args:
        logger: Logger instance
        operation_name: Name of the operation
        
    Returns:
        Decorator function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            with PerformanceLogger(logger, operation_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator

def setup_summary_logger(base_dir: str, module: str) -> logging.Logger:
    """
    Setup summary logger for performance reports.
    
    Args:
        base_dir: Base directory for logs
        module: Module name
        
    Returns:
        Summary logger instance
    """
    try:
        logger = logging.getLogger(f"TradingBot.{module}.summary")
        logger.setLevel(SUMMARY)
        
        if not logger.handlers:
            # Create summary file handler
            summary_path = get_log_path(base_dir, module, level='summary')
            handler = TimedRotatingFileHandler(
                summary_path,
                when='midnight',
                interval=1,
                backupCount=30
            )
            
            formatter = SummaryFormatter('%(asctime)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            
            # Prevent propagation
            logger.propagate = False
        
        return logger
        
    except Exception as e:
        # Return basic logger if setup fails
        basic_logger = logging.getLogger(f"TradingBot.{module}.summary")
        basic_logger.setLevel(SUMMARY)
        return basic_logger

# Global performance logger
_performance_logger = None

def get_performance_logger(base_dir: str = ".") -> logging.Logger:
    """Get global performance logger instance."""
    global _performance_logger
    
    if _performance_logger is None:
        _performance_logger = setup_summary_logger(base_dir, "performance")
    
    return _performance_logger

# Utility functions for common logging patterns
def log_trade(logger: logging.Logger, trade_data: Dict[str, Any], level: str = 'info'):
    """Log trade information in a structured way."""
    log_method = getattr(logger, level.lower(), logger.info)
    log_method("Trade executed", extra={
        'trade_data': trade_data,
        'symbol': trade_data.get('symbol'),
        'timeframe': trade_data.get('timeframe')
    })

def log_signal(logger: logging.Logger, signal_data: Dict[str, Any], level: str = 'info'):
    """Log trading signal in a structured way."""
    log_method = getattr(logger, level.lower(), logger.info)
    log_method("Signal generated", extra={
        'signal_data': signal_data,
        'symbol': signal_data.get('symbol'),
        'timeframe': signal_data.get('timeframe')
    })

def log_error(logger: logging.Logger, error: Exception, context: str = "", 
              extra_data: Dict[str, Any] = None):
    """Log error with context and extra data."""
    extra = extra_data or {}
    extra['error_type'] = type(error).__name__
    extra['error_message'] = str(error)
    extra['context'] = context
    
    logger.error(f"Error in {context}: {error}", extra=extra, exc_info=True)

def log_performance_metrics(logger: logging.Logger, metrics: Dict[str, Any], 
                           operation: str = "operation"):
    """Log performance metrics."""
    logger.info(f"Performance metrics for {operation}", extra={
        'performance_metrics': metrics,
        'operation': operation
    })
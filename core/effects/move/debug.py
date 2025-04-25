"""
Simple debugging utilities for move effects that use print statements.
"""

import functools
import inspect
import time

def print_move_operation(func):
    """Decorator to print information about move operations"""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if hasattr(self, 'name'):
            name = self.name
        else:
            name = self.__class__.__name__
            
        print(f"[Move-{name}] Executing {func.__name__}")
        
        start_time = time.time()
        result = func(self, *args, **kwargs)
        elapsed = (time.time() - start_time) * 1000  # ms
        
        print(f"[Move-{name}] Completed {func.__name__} in {elapsed:.2f}ms")
        
        return result
    return wrapper

def print_async_move_operation(func):
    """Decorator to print information about async move operations"""
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        if hasattr(self, 'name'):
            name = self.name
        else:
            name = self.__class__.__name__
            
        print(f"[Move-{name}] Executing async {func.__name__}")
        
        start_time = time.time()
        result = await func(self, *args, **kwargs)
        elapsed = (time.time() - start_time) * 1000  # ms
        
        print(f"[Move-{name}] Completed async {func.__name__} in {elapsed:.2f}ms")
        
        return result
    return wrapper

def trace_move_state_changes(instance, attr_name, old_value, new_value):
    """Print when a move effect state changes"""
    if hasattr(instance, 'name'):
        name = instance.name
    else:
        name = instance.__class__.__name__
        
    # Get the calling function name
    frame = inspect.currentframe().f_back
    func_name = frame.f_code.co_name if frame else "unknown"
    
    print(f"[Move-{name}] State change in {func_name}: {attr_name} changed from {old_value} to {new_value}")

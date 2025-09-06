"""Base collector class with common functionality."""

import os
import time
import logging
import requests
from typing import Dict, Optional, Any
from datetime import datetime, timezone
from abc import ABC, abstractmethod
from dotenv import load_dotenv

from app.storage.db import update_collection_status

load_dotenv()

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Base class for all data collectors."""
    
    def __init__(self, name: str, base_url: str, rate_limit_delay: float = 1.0):
        """
        Initialize collector.
        
        Args:
            name: Collector name for logging and status tracking
            base_url: Base URL for API requests
            rate_limit_delay: Seconds to wait between requests
        """
        self.name = name
        self.base_url = base_url.rstrip('/')
        self.rate_limit_delay = rate_limit_delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Bitcoin-Health-Scorecard/1.0'
        })
        
    def get(self, endpoint: str, params: Optional[Dict] = None, **kwargs) -> Optional[Dict]:
        """
        Make GET request with error handling and rate limiting.
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            **kwargs: Additional requests arguments
            
        Returns:
            JSON response or None on error
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            response = self.session.get(url, params=params, timeout=30, **kwargs)
            response.raise_for_status()
            
            # Rate limiting
            time.sleep(self.rate_limit_delay)
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"{self.name} request failed for {url}: {e}")
            return None
        except ValueError as e:
            logger.error(f"{self.name} JSON decode failed for {url}: {e}")
            return None
    
    def run(self) -> bool:
        """
        Run the collector and update status.
        
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Starting {self.name} collector")
        
        try:
            self.collect()
            update_collection_status(self.name, success=True)
            logger.info(f"{self.name} collector completed successfully")
            return True
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"{self.name} collector failed: {error_msg}")
            update_collection_status(self.name, success=False, error=error_msg)
            return False
    
    @abstractmethod
    def collect(self):
        """Implement data collection logic."""
        pass
    
    def get_timestamp(self) -> int:
        """Get current Unix timestamp."""
        return int(datetime.now(timezone.utc).timestamp())
    
    def get_date_string(self) -> str:
        """Get current date in YYYY-MM-DD format."""
        return datetime.now(timezone.utc).strftime('%Y-%m-%d')

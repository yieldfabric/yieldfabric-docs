"""
Base service client
"""

import requests
from typing import Any, Dict, Optional

from ..config import YieldFabricConfig
from ..utils.logger import get_logger
from ..utils.serialization import json_safe


class BaseServiceClient:
    """Base class for service clients."""
    
    def __init__(self, base_url: str, config: YieldFabricConfig):
        """
        Initialize service client.
        
        Args:
            base_url: Base URL for the service
            config: YieldFabric configuration
        """
        self.base_url = base_url.rstrip('/')
        self.config = config
        self.logger = get_logger(debug=config.debug)
        self.session = requests.Session()
    
    def _get_headers(
        self,
        token: Optional[str] = None,
        content_type: str = "application/json",
        refresh_token: Optional[str] = None,
    ) -> Dict[str, str]:
        """Get HTTP headers for requests."""
        headers = {"Content-Type": content_type}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if refresh_token:
            headers["X-Refresh-Token"] = refresh_token
        return headers
    
    def _post(
        self,
        endpoint: str,
        data: Dict[str, Any],
        token: Optional[str] = None,
        timeout: Optional[int] = None,
        refresh_token: Optional[str] = None,
    ) -> requests.Response:
        """
        Make POST request to service.
        
        Args:
            endpoint: API endpoint (relative to base_url)
            data: Request data
            token: Optional JWT token
            timeout: Optional request timeout
            
        Returns:
            Response object
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers(token, refresh_token=refresh_token)
        timeout = timeout or self.config.request_timeout
        
        self.logger.api_request("POST", url)
        
        try:
            response = self.session.post(
                url,
                json=json_safe(data),
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()
            self.logger.api_response(response.status_code, True)
            return response
        
        except requests.exceptions.RequestException as e:
            self.logger.api_response(getattr(e.response, 'status_code', 0), False)
            raise
    
    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, 
             token: Optional[str] = None, timeout: Optional[int] = None) -> requests.Response:
        """
        Make GET request to service.
        
        Args:
            endpoint: API endpoint (relative to base_url)
            params: Optional query parameters
            token: Optional JWT token
            timeout: Optional request timeout
            
        Returns:
            Response object
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers(token)
        timeout = timeout or self.config.request_timeout
        
        self.logger.api_request("GET", url)
        
        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()
            self.logger.api_response(response.status_code, True)
            return response
        
        except requests.exceptions.RequestException as e:
            self.logger.api_response(getattr(e.response, 'status_code', 0), False)
            raise
    
    def _post_json_safe(
        self,
        endpoint: str,
        data: Dict[str, Any],
        token: Optional[str] = None,
        *,
        description: str = "",
    ) -> Dict[str, Any]:
        """
        Safe variant of `_post` used by idempotent / error-tolerant
        callers (auth-service admin endpoints, setup-phase mutations).

        Returns the JSON body on success. On HTTP / transport error
        returns a uniform dict:

            {"status": "error", "message": "<reason>"}

        This avoids forcing every caller to wrap `_post` in its own
        try/except + error dict.
        """
        try:
            response = self._post(endpoint, data, token=token)
            return response.json()
        except Exception as e:
            response = getattr(e, "response", None)
            status_code = getattr(response, "status_code", None)
            if response is not None:
                try:
                    body = response.json()
                except Exception:
                    body = response.text
                message = body if body else str(e)
            else:
                message = str(e)
            if description:
                self.logger.error(f"    ❌ {description}: {message}")
            error = {"status": "error", "message": str(message)}
            if status_code is not None:
                error["status_code"] = status_code
            return error

    def _get_json_safe(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None,
        *,
        description: str = "",
        default: Optional[Any] = None,
    ) -> Any:
        """
        Safe variant of `_get`. Returns parsed JSON on success; on HTTP
        error returns `default` (defaulting to None) and logs if a
        `description` is supplied.
        """
        try:
            response = self._get(endpoint, params=params, token=token)
            return response.json()
        except Exception as e:
            if description:
                self.logger.debug(f"{description} failed: {e}")
            return default

    def _request_json_safe(
        self,
        method: str,
        endpoint: str,
        *,
        token: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute an arbitrary JSON REST request and preserve its HTTP outcome.

        This is intended for semantic test executors that need to exercise a
        denial matrix across several endpoints. It never raises and always
        returns ``{ok, status_code, body}``.
        """
        verb = (method or "").strip().upper()
        if verb not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return {
                "ok": False,
                "status_code": 0,
                "body": {"error": f"unsupported HTTP method: {method}"},
            }
        if not endpoint.startswith("/"):
            return {
                "ok": False,
                "status_code": 0,
                "body": {"error": "endpoint must start with '/'"},
            }

        url = f"{self.base_url}{endpoint}"
        self.logger.api_request(verb, url)
        try:
            kwargs: Dict[str, Any] = {
                "headers": self._get_headers(token),
                "params": params,
                "timeout": self.config.request_timeout,
            }
            if data is not None:
                kwargs["json"] = json_safe(data)
            response = self.session.request(verb, url, **kwargs)
            ok = 200 <= response.status_code < 300
            self.logger.api_response(response.status_code, ok)
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text
            return {
                "ok": ok,
                "status_code": response.status_code,
                "body": body,
            }
        except requests.exceptions.RequestException as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", 0) or 0
            body: Any = str(exc)
            if response is not None:
                try:
                    body = response.json()
                except ValueError:
                    body = response.text or str(exc)
            self.logger.api_response(status_code, False)
            return {"ok": False, "status_code": status_code, "body": body}

    def check_health(self, timeout: Optional[int] = None) -> bool:
        """
        Check if service is healthy.
        
        Args:
            timeout: Optional health check timeout
            
        Returns:
            True if service is healthy
        """
        timeout = timeout or self.config.health_check_timeout
        
        try:
            # Try /health endpoint first
            response = self.session.get(
                f"{self.base_url}/health",
                timeout=timeout
            )
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        
        try:
            # Fallback to base URL
            response = self.session.get(
                self.base_url,
                timeout=timeout
            )
            return 200 <= response.status_code < 500
        except requests.exceptions.RequestException:
            return False
    
    def close(self):
        """Close session."""
        self.session.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

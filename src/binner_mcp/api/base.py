"""Core authentication, session lifecycle, and request execution for Binner API."""

import logging
import threading
from typing import Any, Dict, Optional
import requests

from binner_mcp.api.exceptions import (
    BinnerAPIError,
    BinnerAuthError,
    BinnerConnectionError,
    BinnerNotFoundError,
)
from binner_mcp.api.models import (
    AuthenticatedTokens,
    AuthenticationRequest,
    UserContext,
)
from binner_mcp.common.http import BaseHttpClient
from binner_mcp.common.logging import log_trace, sanitize_for_trace

logger = logging.getLogger("binner_mcp.api.client")


class BaseBinnerClient(BaseHttpClient):
    """
    Core HTTP proxy client for local Binner instances.

    Manages connection pooling, cookie-bound token refreshes, re-entrant locking,
    and adaptive lifecycle request callbacks.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8090",
        username: str = "admin",
        password: str = "admin",
        timeout: float = 10.0,
        **kwargs: Any,
    ) -> None:
        lock = threading.RLock()
        super().__init__(
            base_url=base_url,
            timeout=timeout,
            user_agent="Binner-MCP-Proxy/1.0",
            lock=lock,
        )
        self.username = username
        self.password = password

        # Additional default headers expected by Binner
        self.session.headers.update({
            "Content-Type": "application/json",
        })

        self.jwt_token: Optional[str] = None
        self.tokens: Optional[AuthenticatedTokens] = None
        self._is_logged_in: bool = False
        self.__current_auto_login: bool = True
        # self._last_auth_time: float = 0.0

    @property
    def is_logged_in(self) -> bool:
        """Check if proxy currently holds an active login session."""
        return self._is_logged_in

    # === Adaptive Lifecycle Event Hooks ===

    def _before_request(
        self,
        method: str,
        path: str,
        url: str,
        kwargs: Dict[str, Any],
    ) -> None:
        super()._before_request(method, path, url, kwargs)
        if self.__current_auto_login and not self._is_logged_in:
            self.login()

    def _on_response(
        self,
        response: requests.Response,
        method: str,
        path: str,
        url: str,
        timeout: float,
        kwargs: Dict[str, Any],
    ) -> Optional[requests.Response]:
        super_resp = super()._on_response(response, method, path, url, timeout, kwargs)
        if super_resp is not None:
            return super_resp

        is_unauth_error = response.status_code == 401 or (
            response.status_code == 500
            and (
                "UserContextUnauthorizedException" in response.text
                or "requires valid user context" in response.text
            )
        )
        if (
            is_unauth_error
            and self.__current_auto_login
            and not path.startswith("api/authentication")
        ):
            logger.warning(
                "Access token expired or unauthorized user context (%d). Initiating token refresh...",
                response.status_code,
            )
            if self._handle_token_refresh():
                log_trace(logger, "Retrying request %s %s after token refresh", method, url)
                retry_resp = self.session.request(method, url, timeout=timeout, **kwargs)
                log_trace(logger, "Post-refresh response %d from %s %s", retry_resp.status_code, method, url)
                return retry_resp

        return None

    def _handle_response_status(
        self,
        response: requests.Response,
        method: str,
        path: str,
    ) -> None:
        if response.status_code == 404:
            raise BinnerNotFoundError(f"Resource not found: {path}", details=response.text)

        if response.status_code in (401, 403) or (
            response.status_code == 500
            and (
                "UserContextUnauthorizedException" in response.text
                or "requires valid user context" in response.text
            )
        ):
            self._is_logged_in = False
            raise BinnerAuthError(f"Authentication failure ({response.status_code}) on {path}: {response.text}")

        if not response.ok:
            raise BinnerAPIError(
                f"API request failed on {path}",
                status_code=response.status_code,
                response_text=response.text,
            )

    def _handle_request_exception(
        self,
        exc: requests.RequestException,
        method: str,
        url: str,
    ) -> None:
        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            self._is_logged_in = False
            logger.error("Connection error on %s %s: %s", method, url, exc)
            raise BinnerConnectionError(f"Unable to reach Binner instance at {self.base_url}") from exc

        if isinstance(exc, (BinnerNotFoundError, BinnerAuthError, BinnerAPIError)):
            raise exc

        logger.error("HTTP exception on %s %s: %s", method, url, exc)
        raise BinnerAPIError(f"HTTP request error: {exc}", status_code=0, response_text=str(exc)) from exc

    def _execute_request(
        self,
        method: str,
        path: str,
        auto_login: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Execute an HTTP request with automatic 401 recovery and strict error mapping.
        Synchronously serialized by self._lock.
        """
        self.__current_auto_login = auto_login
        return super()._execute_request(method, path, **kwargs)


    # === Authentication & Identity Methods ===

    def ping(self) -> bool:
        """Verify database connectivity via anonymous ping endpoint."""
        url = f"{self.base_url}/api/ping"
        log_trace(logger, "GET %s (anonymous ping)", url)
        try:
            resp = self.session.get(url, timeout=min(5.0, self.timeout))
            is_pong = resp.status_code == 200 and resp.text.strip().strip('"') == "pong"
            if is_pong:
                logger.info("Binner instance ping successful at %s", self.base_url)
            else:
                logger.warning("Ping returned status %d: %s", resp.status_code, resp.text)
            return is_pong
        except requests.exceptions.RequestException as e:
            logger.debug("Ping failed against %s: %s", self.base_url, e)
            return False

    def login(self) -> AuthenticatedTokens:
        """
        Authenticate with username and password.

        Stores JWT in session headers and refresh token in cookie jar.
        """
        with self._lock:
            login_url = f"{self.base_url}/api/authentication/login"
            payload = AuthenticationRequest(
                username=self.username,
                password=self.password,
            ).model_dump(by_alias=True, exclude_none=True)

            logger.info("Authenticating user '%s' at %s", self.username, self.base_url)
            log_trace(logger, "POST %s payload=%s", login_url, sanitize_for_trace(payload))

            try:
                resp = self.session.post(login_url, json=payload, timeout=self.timeout)
                if resp.status_code in (401, 403):
                    self._is_logged_in = False
                    raise BinnerAuthError(f"Invalid credentials for user '{self.username}'")

                resp.raise_for_status()
                data = resp.json()
                tokens = AuthenticatedTokens.model_validate(data)

                if not tokens.jwt_token:
                    self._is_logged_in = False
                    raise BinnerAuthError("No jwtToken received in login response payload")

                self.jwt_token = tokens.jwt_token
                self.tokens = tokens
                self.session.headers.update({"Authorization": f"Bearer {self.jwt_token}"})
                self._is_logged_in = True
                # self._last_auth_time = time.time()
                logger.info("Authentication successful for user '%s'", self.username)
                return tokens
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as ce:
                self._is_logged_in = False
                logger.error("Connection error during login: %s", ce)
                raise BinnerConnectionError(f"Cannot connect to Binner instance at {self.base_url}") from ce
            except requests.exceptions.RequestException as re:
                self._is_logged_in = False
                logger.error("Login request failed: %s", re)
                raise BinnerAuthError(f"Login request failed: {re}") from re

    def logout(self) -> bool:
        """Log out the current session and clear local credentials."""
        with self._lock:
            logout_url = f"{self.base_url}/api/authentication/logout"
            try:
                if self._is_logged_in:
                    log_trace(logger, "POST %s", logout_url)
                    self.session.post(logout_url, timeout=self.timeout)
            except requests.exceptions.RequestException as e:
                logger.debug("Logout request error (suppressed): %s", e)
            finally:
                self.jwt_token = None
                self.tokens = None
                self._is_logged_in = False
                self.session.headers.pop("Authorization", None)
                self.session.cookies.clear()
                logger.info("Session logged out.")
            return True

    def _handle_token_refresh(self) -> bool:
        """
        Refresh JWT via POST /api/authentication/refresh-token using cookie jar.

        Falls back to explicit login credentials if cookie is missing or refresh fails.
        """
        with self._lock:
            refresh_url = f"{self.base_url}/api/authentication/refresh-token"
            has_refresh_cookie = "refreshToken" in self.session.cookies.get_dict()

            if not has_refresh_cookie:
                logger.warning("No refreshToken cookie found in session jar; falling back to explicit login.")
                tokens = self.login()
                return tokens.jwt_token is not None

            logger.debug("Attempting access token refresh via cookie...")
            log_trace(logger, "POST %s (refresh token)", refresh_url)
            try:
                resp = self.session.post(refresh_url, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    tokens = AuthenticatedTokens.model_validate(data)
                    if tokens.jwt_token:
                        self.jwt_token = tokens.jwt_token
                        self.tokens = tokens
                        self.session.headers.update({"Authorization": f"Bearer {self.jwt_token}"})
                        self._is_logged_in = True
                        # self._last_auth_time = time.time()
                        logger.debug("Access token refreshed successfully.")
                        return True

                logger.warning(
                    "Refresh endpoint returned HTTP %d. Falling back to explicit login.",
                    resp.status_code,
                )
                tokens = self.login()
                return tokens.jwt_token is not None
            except (requests.exceptions.RequestException, ValueError, KeyError) as e:
                logger.warning("Token refresh error (%s). Falling back to explicit login.", e)
                tokens = self.login()
                return tokens.jwt_token is not None

    def get_identity(self) -> UserContext:
        """Fetch currently authenticated user context."""
        resp = self._execute_request("GET", "/api/authentication/identity")
        return UserContext.model_validate(resp.json())

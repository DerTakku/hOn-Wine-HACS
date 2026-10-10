"""Minimal hOn cloud client: CIAM login, appliance list, command definitions, context, send."""
import base64
import hashlib
import logging
import secrets
import time
from datetime import UTC, datetime

import aiohttp

from .const import API_URL, APP_VERSION, DEVICE_MODEL, OS, OS_VERSION, USER_AGENT

_LOGGER = logging.getLogger(__name__)

# CIAM access tokens expire after ~15 minutes, so refresh well before that.
SESSION_TIMEOUT = 600  # seconds


class HonError(Exception):
    """Login rejected, unexpected cloud response, or command refused."""


def build_settings_params(definition: dict, state: dict, changes: dict) -> dict:
    """Return the complete parameter set for a `settings` command.

    The cellar resets every parameter it does not receive to its default. That is
    what used to overwrite the zone temperatures when only `lightStatus` was sent.
    So every parameter is sent: the requested change, fixed values, and the value
    the cellar reports right now for everything else. If a current value is
    unknown, nothing is sent, because guessing could reset a zone.
    """
    params, missing = {}, []
    for key, spec in definition.get("parameters", {}).items():
        if key in changes:
            params[key] = changes[key]
        elif spec.get("typology") == "fixed":
            params[key] = spec.get("fixedValue")
        elif state.get(key) not in (None, ""):
            params[key] = state[key]
        else:
            missing.append(key)
    if missing:
        raise HonError(
            f"not sent, the current value of {', '.join(missing)} is unknown "
            "and sending without it could reset the zone temperatures"
        )
    return params


class HonApi:
    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._mobile_id = secrets.token_hex(8)
        self._cognito_token = ""
        self._id_token = ""
        self._login_time = float("-inf")

    @property
    def _headers(self) -> dict:
        return {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "cognito-token": self._cognito_token,
            "id-token": self._id_token,
        }

    async def login(self) -> None:
        """Log in through /ciam/authorize + /ciam/token (PKCE), as the app does since 2026-06."""
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()

        # 1) Submit credentials, receive a one-time session id.
        # Errors are re-raised without the URL: its query string holds the password.
        params = {"username": self._email, "password": self._password, "code_challenge": challenge}
        try:
            async with self._session.get(
                f"{API_URL}/ciam/authorize", params=params, headers={"User-Agent": USER_AGENT}
            ) as resp:
                status = resp.status
                session_id = (await resp.json()).get("session_id") if status == 200 else None
        except aiohttp.ClientResponseError as err:
            raise HonError(f"CIAM authorize failed (HTTP {err.status})") from None
        if not session_id:
            raise HonError(f"CIAM authorize returned no session (HTTP {status}), check email/password")

        # 2) Exchange the session id (+ PKCE verifier) for the tokens
        async with self._session.post(
            f"{API_URL}/ciam/token",
            json={"session_id": session_id, "code_verifier": verifier},
            headers={"User-Agent": USER_AGENT},
        ) as resp:
            try:
                tokens = (await resp.json())["tokens"]
                self._cognito_token = tokens["cognito_token"]
                self._id_token = tokens["id_token"]
            except (KeyError, TypeError, aiohttp.ContentTypeError) as err:
                raise HonError(f"Unexpected /ciam/token response (HTTP {resp.status})") from err
        self._login_time = time.monotonic()

    async def _ensure_login(self) -> None:
        if time.monotonic() - self._login_time > SESSION_TIMEOUT:
            await self.login()

    async def get_appliances(self) -> list[dict]:
        await self._ensure_login()
        url = f"{API_URL}/unified-api/v1/view/appliance-list"
        async with self._session.post(url, headers=self._headers, json={"deviceId": "homeassistant"}) as resp:
            data = await resp.json()
        try:
            appliances = data["modules"]["applianceList"]["payload"]["appliances"]
        except (KeyError, TypeError) as err:
            raise HonError(f"Unexpected appliance list: {str(data)[:300]}") from err
        return [a for a in appliances if "macAddress" in a and "applianceTypeName" in a]

    async def get_commands(self, appliance: dict) -> dict:
        """Command definitions (incl. `settings` and its parameters) for this model."""
        await self._ensure_login()
        params = {
            "applianceType": appliance["applianceTypeId"],
            "code": appliance["code"],
            "applianceModelId": appliance["applianceModelId"],
            "firmwareId": appliance["eepromId"],
            "macAddress": appliance["macAddress"],
            "fwVersion": appliance["fwVersion"],
            "os": OS,
            "appVersion": APP_VERSION,
            "series": appliance.get("series", ""),
        }
        async with self._session.get(
            f"{API_URL}/commands/v1/retrieve", params=params, headers=self._headers
        ) as resp:
            payload = (await resp.json()).get("payload", {})
        if payload.get("resultCode") != "0":
            raise HonError(f"No command definitions (resultCode {payload.get('resultCode')})")
        return payload

    async def get_context(self, appliance: dict) -> dict:
        """Current state; `shadow.parameters.<name>.parNewVal` holds each value."""
        await self._ensure_login()
        params = {
            "macAddress": appliance["macAddress"],
            "applianceType": appliance["applianceTypeName"],
            "category": "CYCLE",
        }
        async with self._session.get(
            f"{API_URL}/commands/v1/context", params=params, headers=self._headers
        ) as resp:
            return (await resp.json()).get("payload", {})

    async def send_command(
        self, appliance: dict, options: dict, command: str, parameters: dict, ancillary: dict
    ) -> None:
        await self._ensure_login()
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        mac = appliance["macAddress"]
        data = {
            "macAddress": mac,
            "timestamp": now,
            "commandName": command,
            "transactionId": f"{mac}_{now}",
            "applianceOptions": options,
            "device": {
                "mobileId": self._mobile_id,
                "mobileOs": OS,
                "osVersion": OS_VERSION,
                "appVersion": APP_VERSION,
                "deviceModel": DEVICE_MODEL,
            },
            "attributes": {"channel": "mobileApp", "origin": "standardProgram", "energyLabel": "0"},
            "ancillaryParameters": ancillary,
            "parameters": parameters,
            "applianceType": appliance["applianceTypeName"],
        }
        _LOGGER.debug("Sending command: %s", data)
        async with self._session.post(f"{API_URL}/commands/v1/send", headers=self._headers, json=data) as resp:
            result = await resp.json()
        _LOGGER.debug("Command result: %s", result)
        if result.get("payload", {}).get("resultCode") != "0":
            raise HonError(f"hOn rejected the command: {result}")

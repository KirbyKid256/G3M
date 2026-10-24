"""GameBanana Remote Install: polls the paired member's queue and queues each mod for download."""

import logging
import re
import threading

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from adapters.gamebanana_adapter import GameBananaAPI
from config.config import GAMEBANANA_API_BASE, NETWORK_TIMEOUT_MEDIUM
from utils.network_utils import get_session

logger = logging.getLogger(__name__)

APP_ID = "G3M"
CONFIG_KEY = "gb_remote_install"
POLL_INTERVAL_MS = 60_000
# "{downloadURL},{modType},{modID}", the same shape as a 1-click link, with or without the protocol
_ENTRY = re.compile(r"(?:https?:?//)?(?:www\.)?gamebanana\.com/mmdl/(\d+),(Mod|Wip),(\d+)", re.IGNORECASE)


class RemoteInstallService(QObject):
    mod_ready = pyqtSignal(object, dict)

    def __init__(self, app_state, settings_service, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.settings_service = settings_service
        self._busy = False
        self._rejected = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.poll)

    def pair(self, member_id: str, secret_key: str) -> None:
        self.app_state.local_config[CONFIG_KEY] = {"member_id": member_id, "secret_key": secret_key}
        self.settings_service.write_local_config()
        self._rejected = False
        self.start()

    def start(self) -> None:
        if self.app_state.local_config.get(CONFIG_KEY):
            self._timer.start()
            self.poll()

    def poll(self) -> None:
        credentials = self.app_state.local_config.get(CONFIG_KEY)
        if self._rejected or not credentials:
            self._timer.stop()
        elif not self._busy:
            self._busy = True
            threading.Thread(target=self._fetch, args=(credentials,), daemon=True).start()

    def _fetch(self, credentials: dict) -> None:
        url = f"{GAMEBANANA_API_BASE}/RemoteInstall/{credentials['member_id']}/{credentials['secret_key']}/{APP_ID}"
        try:
            response = get_session().get(url, timeout=NETWORK_TIMEOUT_MEDIUM)
            if 400 <= response.status_code < 500:
                self._rejected = True  # a revoked key would only be retried every minute
            response.raise_for_status()
            entries = response.json()
            for entry in entries if isinstance(entries, list) else []:
                self._queue(entry)
        except Exception as error:
            # The URL carries the secret key, so never log the exception text.
            logger.warning("Remote install poll failed: %s", type(error).__name__)
        finally:
            self._busy = False

    def _queue(self, entry: object) -> None:
        match = _ENTRY.fullmatch(entry) if isinstance(entry, str) else None
        if not match:
            logger.warning("Remote install: ignored entry %r", entry)
            return
        file_id, item_type, mod_id = match.groups()
        try:
            mod = GameBananaAPI().get_installable_mod(int(mod_id), item_type.capitalize())
            file = next(f for f in mod.gamebanana_supported_files if str(f["id"]) == file_id)
        except Exception as error:
            logger.warning("Remote install: could not queue %s: %s", entry, error)
            return
        self.mod_ready.emit(mod, file)

"""
Thread-safe Global Robot State Manager
Maintains operational state, emotional expressions, audio/speaker flags,
ultrasonic sensor readings, and conversation history.
"""

import time
import socket
import threading
from enum import Enum
from typing import Dict, Any, List, Optional, Callable


class RobotState(str, Enum):
    IDLE = "idle"
    WAKING = "waking"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


class Emotion(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    THINKING = "thinking"
    LISTENING = "listening"
    SPEAKING = "speaking"
    ERROR = "error"


class StateManager:
    """Thread-safe singleton-style state manager for Easibot."""

    def __init__(self, default_language: str = "auto", speaker_enabled: bool = True):
        self._lock = threading.RLock()
        
        # Operational states
        self._state: RobotState = RobotState.IDLE
        self._emotion: Emotion = Emotion.NEUTRAL
        self._active_language: str = default_language
        self._detected_language: str = "en"
        
        # Hardware & Proximity
        self._current_distance_cm: float = -1.0
        self._last_wake_time: float = 0.0
        self._speaker_enabled: bool = speaker_enabled
        self._mock_mode: bool = False
        
        # Conversation history
        self._last_user_query: str = ""
        self._last_reply_native: str = "Ready to assist you!"
        self._last_reply_english: str = "Ready to assist you!"
        self._last_reply_romanized: str = "Ready to assist you!"
        self._messages: List[Dict[str, Any]] = []
        self._max_messages: int = 40
        
        # Network & IP
        self._ip_address: str = self._detect_local_ip()
        self._wifi_connected: bool = self._ip_address not in ("127.0.0.1", "Unavailable")
        
        # Observers/listeners
        self._state_change_callbacks: List[Callable[[RobotState, Emotion], None]] = []

    def _detect_local_ip(self) -> str:
        """Finds primary local IP address without making external requests."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Doesn't need to be reachable, just gets the default interface routing
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # State & Emotion Getters / Setters
    @property
    def state(self) -> RobotState:
        with self._lock:
            return self._state

    @property
    def emotion(self) -> Emotion:
        with self._lock:
            return self._emotion

    def set_state(self, new_state: RobotState, new_emotion: Optional[Emotion] = None):
        """Update operational state and optionally the emotion."""
        callbacks_to_fire = []
        with self._lock:
            self._state = new_state
            if new_emotion:
                self._emotion = new_emotion
            elif new_state == RobotState.IDLE:
                self._emotion = Emotion.NEUTRAL
            elif new_state == RobotState.LISTENING:
                self._emotion = Emotion.LISTENING
            elif new_state == RobotState.THINKING:
                self._emotion = Emotion.THINKING
            elif new_state == RobotState.SPEAKING:
                self._emotion = Emotion.SPEAKING
            elif new_state == RobotState.ERROR:
                self._emotion = Emotion.ERROR
            
            current_s = self._state
            current_e = self._emotion
            callbacks_to_fire = list(self._state_change_callbacks)

        # Notify observers outside the lock
        for cb in callbacks_to_fire:
            try:
                cb(current_s, current_e)
            except Exception:
                pass

    def set_emotion(self, emotion: Emotion):
        with self._lock:
            self._emotion = emotion

    # Language
    @property
    def active_language(self) -> str:
        with self._lock:
            return self._active_language

    def set_active_language(self, lang_code: str):
        with self._lock:
            if lang_code in ("auto", "en", "te", "hi"):
                self._active_language = lang_code

    @property
    def detected_language(self) -> str:
        with self._lock:
            return self._detected_language

    def set_detected_language(self, lang_code: str):
        with self._lock:
            self._detected_language = lang_code

    # Ultrasonic Distance
    @property
    def current_distance(self) -> float:
        with self._lock:
            return self._current_distance_cm

    def update_distance(self, distance_cm: float):
        with self._lock:
            self._current_distance_cm = round(distance_cm, 1)

    # Proximity Wake-up Cooldown
    def can_trigger_wake(self, cooldown_sec: float) -> bool:
        with self._lock:
            now = time.time()
            if self._state == RobotState.IDLE and (now - self._last_wake_time) >= cooldown_sec:
                self._last_wake_time = now
                return True
            return False

    def mark_wake_triggered(self):
        with self._lock:
            self._last_wake_time = time.time()

    # Speaker Control
    @property
    def speaker_enabled(self) -> bool:
        with self._lock:
            return self._speaker_enabled

    def set_speaker_enabled(self, enabled: bool):
        with self._lock:
            self._speaker_enabled = enabled

    @property
    def mock_mode(self) -> bool:
        with self._lock:
            return self._mock_mode

    def set_mock_mode(self, mock: bool):
        with self._lock:
            self._mock_mode = mock

    # Dialogue Updates & Conversation History
    def record_turn(
        self,
        user_query: str,
        reply_native: str,
        reply_english: str,
        reply_romanized: str,
        emotion: str,
        detected_language: str
    ):
        with self._lock:
            self._last_user_query = user_query
            self._last_reply_native = reply_native
            self._last_reply_english = reply_english
            self._last_reply_romanized = reply_romanized
            self._detected_language = detected_language
            
            try:
                self._emotion = Emotion(emotion.lower())
            except ValueError:
                self._emotion = Emotion.NEUTRAL

            timestamp = time.strftime("%H:%M:%S")

            # Add user message if query exists
            if user_query.strip():
                self._messages.append({
                    "id": len(self._messages) + 1,
                    "sender": "user",
                    "text": user_query,
                    "language": detected_language,
                    "timestamp": timestamp
                })

            # Add robot message
            self._messages.append({
                "id": len(self._messages) + 1,
                "sender": "robot",
                "text": reply_native,
                "english": reply_english,
                "romanized": reply_romanized,
                "emotion": self._emotion.value,
                "language": detected_language,
                "timestamp": timestamp
            })

            # Trim old history
            if len(self._messages) > self._max_messages:
                self._messages = self._messages[-self._max_messages:]

    @property
    def last_reply_native(self) -> str:
        with self._lock:
            return self._last_reply_native

    @property
    def last_reply_romanized(self) -> str:
        with self._lock:
            return self._last_reply_romanized

    @property
    def last_reply_english(self) -> str:
        with self._lock:
            return self._last_reply_english

    def add_state_listener(self, callback: Callable[[RobotState, Emotion], None]):
        """Register a callback for state changes."""
        with self._lock:
            self._state_change_callbacks.append(callback)

    def to_dict(self) -> Dict[str, Any]:
        """Snapshot of current state for REST API & web dashboard."""
        with self._lock:
            return {
                "state": self._state.value,
                "emotion": self._emotion.value,
                "active_language": self._active_language,
                "detected_language": self._detected_language,
                "distance_cm": self._current_distance_cm,
                "speaker_enabled": self._speaker_enabled,
                "mock_mode": self._mock_mode,
                "ip_address": self._ip_address,
                "wifi_connected": self._wifi_connected,
                "last_user_query": self._last_user_query,
                "last_reply_native": self._last_reply_native,
                "last_reply_english": self._last_reply_english,
                "last_reply_romanized": self._last_reply_romanized,
                "messages": list(self._messages)
            }

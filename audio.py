"""Optional USB microphone capture for browser audio playback.

This module captures audio from a USB microphone (or any ALSA/Pulse device) and exposes
recent audio chunks as a WAV stream. It is intentionally light-weight and disabled by default.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

LOG = logging.getLogger("security_camera.audio")

try:
    import pyaudio  # type: ignore
except Exception:  # pragma: no cover - optional dependency on Pi OS
    pyaudio = None


class MicrophoneStream:
    def __init__(self, config):
        self.config = config
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest_chunk: bytes = b""
        self._lock = threading.Lock()

    def enabled(self) -> bool:
        return bool(self.config.as_dict().get("audio", {}).get("enabled", False))

    def start(self) -> None:
        if not self.enabled():
            return
        if pyaudio is None:
            LOG.warning("pyaudio not installed; microphone audio is disabled")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="MicrophoneCapture")
        self._thread.start()
        LOG.info("Microphone capture started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        LOG.info("Microphone capture stopped")

    def latest_chunk(self) -> bytes:
        with self._lock:
            return self._latest_chunk

    def _run(self) -> None:
        pa = pyaudio.PyAudio()
        rate = int(self.config.as_dict().get("audio", {}).get("sample_rate", 16000))
        channels = int(self.config.as_dict().get("audio", {}).get("channels", 1))
        chunk = int(self.config.as_dict().get("audio", {}).get("chunk_size", 4096))
        device_index = int(self.config.as_dict().get("audio", {}).get("device_index", -1))
        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=None if device_index < 0 else device_index,
                frames_per_buffer=chunk,
            )
            LOG.info("Opened microphone device index=%s rate=%s channels=%s chunk=%s", device_index, rate, channels, chunk)
            while not self._stop_event.is_set():
                try:
                    frames = stream.read(chunk, exception_on_overflow=False)
                    with self._lock:
                        self._latest_chunk = frames
                except Exception:
                    LOG.exception("Microphone read failed")
                    time.sleep(0.25)
        except Exception:
            LOG.exception("Unable to open microphone input")
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            pa.terminate()

    def wav_header(self, frame_count: int = 0) -> bytes:
        rate = int(self.config.as_dict().get("audio", {}).get("sample_rate", 16000))
        channels = int(self.config.as_dict().get("audio", {}).get("channels", 1))
        sample_bits = 16
        byte_rate = rate * channels * sample_bits // 8
        block_align = channels * sample_bits // 8
        data_size = frame_count * block_align
        header = bytearray(44)
        header[0:4] = b'RIFF'
        header[4:8] = (36 + data_size).to_bytes(4, 'little')
        header[8:12] = b'WAVE'
        header[12:16] = b'fmt '
        header[16:20] = (16).to_bytes(4, 'little')
        header[20:22] = (1).to_bytes(2, 'little')
        header[22:24] = channels.to_bytes(2, 'little')
        header[24:28] = rate.to_bytes(4, 'little')
        header[28:32] = byte_rate.to_bytes(4, 'little')
        header[32:34] = block_align.to_bytes(2, 'little')
        header[34:36] = sample_bits.to_bytes(2, 'little')
        header[36:40] = b'data'
        header[40:44] = data_size.to_bytes(4, 'little')
        return bytes(header)

    def stream_wav(self):
        if not self.enabled():
            return
        yield self.wav_header()
        while not self._stop_event.is_set():
            chunk = self.latest_chunk()
            if chunk:
                yield chunk
            time.sleep(0.05)

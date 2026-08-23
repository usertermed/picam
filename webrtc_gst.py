"""GStreamer-based WebRTC signaling helper.

This module uses GObject Introspection (python3-gi) and GStreamer webrtcbin to
create a pipeline that streams the local camera and microphone to a browser
peer by answering the browser's SDP offer.

Note: This code must run on the Raspberry Pi with GStreamer and gir bindings
installed (python3-gi, gir1.2-gstreamer-1.0, gstreamer1.0-plugins-bad, etc.).
It is written to be run synchronously from a Flask request handler and will
block while creating the pipeline and generating an SDP answer.

Testing and tuning on-device is required because pipelines and element names
can vary by platform and installed plugins.
"""
from __future__ import annotations

import logging
import threading
import time

LOG = logging.getLogger("security_camera.webrtc_gst")

try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstWebRTC', '1.0')
    gi.require_version('GstSdp', '1.0')
    from gi.repository import Gst, GstSdp, GstWebRTC, GObject
except Exception:
    Gst = None
    GstSdp = None
    GstWebRTC = None
    GObject = None


_started = False
_start_lock = threading.Lock()


def _ensure_init():
    global _started
    if _started:
        return
    with _start_lock:
        if _started:
            return
        if Gst is None:
            raise RuntimeError("GStreamer python bindings not available. Install python3-gi and gir1.2-gstreamer-1.0.")
        Gst.init(None)
        _started = True
        LOG.info("GStreamer initialized")


def create_answer(offer_sdp: str, use_audio: bool = False, camera_device: str = "/dev/video0") -> str:
    """Create a GStreamer pipeline that answers the given SDP offer and return the SDP answer text.

    This function returns the SDP text for the answer. It may block for a few seconds
    while GStreamer constructs and negotiates the pipeline. The caller is responsible
    for ensuring the pipeline continues running if they want an active stream. For
    our use-case the pipeline will be left in PLAYING state by this function.
    """
    _ensure_init()

    video_caps = "video/x-raw,format=I420"

    # Build pipeline description. This is a best-effort string that should work on
    # systems with v4l2src, vp8 encoder, and opus encoder available. Adjust encoders
    # if needed on the Pi (e.g., use x264enc for H264 if vp8 isn't available).
    parts = []
    parts.append("webrtcbin name=webrtcbin stun-server=stun://stun.l.google.com:19302")

    # Video branch from camera -> convert -> encode -> pay -> webrtcbin
    video_branch = (f"v4l2src device={camera_device} ! videoconvert ! videorate ! "
                    f"video/x-raw,format=I420 ! queue ! vp8enc deadline=1 cpu-used=5 ! rtpvp8pay ! "
                    f"application/x-rtp,media=video,encoding-name=VP8,payload=96 ! queue ! webrtcbin.")
    parts.insert(0, video_branch)

    if use_audio:
        audio_branch = ("pulsesrc ! audioconvert ! audioresample ! queue ! opusenc ! rtpopuspay ! "
                        "application/x-rtp,media=audio,encoding-name=OPUS,payload=97 ! queue ! webrtcbin.")
        parts.insert(0, audio_branch)

    pipeline_desc = ' '.join(parts)
    LOG.debug("GStreamer pipeline: %s", pipeline_desc)

    pipeline = Gst.parse_launch(pipeline_desc)
    if not pipeline:
        raise RuntimeError("Failed to create GStreamer pipeline")

    webrtc = pipeline.get_by_name('webrtcbin')
    if not webrtc:
        # Some systems may name it differently; search for element with factory "webrtcbin"
        for elem in pipeline.iterate_elements():
            try:
                if elem.get_factory().get_name() == 'webrtcbin':
                    webrtc = elem
                    break
            except Exception:
                continue
    if not webrtc:
        raise RuntimeError('webrtcbin element not found in pipeline')

    # Helper: convert SDP text to GstWebRTC session description
    def sdp_from_text(text: str):
        res, sdp = GstSdp.sdp_message_new()
        # GstSdp provides parse functions via GstSdp.sdp_message_new_from_text in some versions
        try:
            sdp = GstSdp.SDPMessage.new_from_text(text)
            return GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.OFFER, sdp)
        except Exception:
            # Try alternative parsing
            res, sdp = GstSdp.sdp_message_new()
            if res:
                return GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.OFFER, sdp)
            raise

    # Set pipeline to playing early to allow elements to negotiate properly
    pipeline.set_state(Gst.State.PLAYING)

    # Create GST structures for setting remote description
    offer_sdp_msg = GstSdp.SDPMessage.new_from_text(offer_sdp)
    offer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.OFFER, offer_sdp_msg)

    promise = Gst.Promise.new()
    webrtc.emit('set-remote-description', offer, promise)
    promise.interrupt()

    # Create answer
    ans_promise = Gst.Promise.new()
    webrtc.emit('create-answer', None, ans_promise)
    # wait for answer
    ret = ans_promise.wait(5 * Gst.SECOND)
    if ret != Gst.PromiseResult.REPLIED:
        LOG.warning('create-answer promise result not REPLIED: %s', ret)

    reply = ans_promise.get_reply()
    answer = reply.get_value('answer')
    if not answer:
        raise RuntimeError('Failed to obtain answer from webrtcbin')

    # answer is a GstWebRTC.WebRTCSessionDescription
    sdp_text = answer.sdp.as_text()

    # Keep pipeline playing — caller needs to keep reference if they want it to continue.
    LOG.info('Generated SDP answer (length=%d)', len(sdp_text))
    # We intentionally do not set pipeline to NULL so that stream keeps running.
    return sdp_text

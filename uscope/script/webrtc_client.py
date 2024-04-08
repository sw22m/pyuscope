"""

"""
from PyQt5.QtCore import pyqtSignal
import random
import websockets
import asyncio
import json
import gi
import ssl
import time
from threading import Thread
gi.require_version('Gst', '1.0')
from gi.repository import Gst
gi.require_version('GstWebRTC', '1.0')
from gi.repository import GstWebRTC
gi.require_version('GstSdp', '1.0')
from gi.repository import GstSdp

STUN_SERVER = "stun://stun.l.google.com:19302"

Gst.init(None)


class MyWebRtcBin(Gst.Bin):

    def __init__(
        self,
        gst_element_name=None,
        incoming_wh=None,
    ):
        super().__init__()

        # self.player = player
        self.gst_element_name = gst_element_name
        # Used to fit incoming stream to window
        self.videoscale = None
        self.videocrop = None
        # Tell the videoscale the window size we need
        self.capsfilter = None
        #
        self.videoflip = None

        # H264 to RTP to WebRTC
        self.videoconvert = None
        self.openh264enc = None
        self.h264parse = None
        self.rtph264pay = None
        self.webrtc = None

    def create_elements(self):
        self.videocrop = Gst.ElementFactory.make("videocrop")
        assert self.videocrop
        self.add(self.videocrop)

        self.videoscale = Gst.ElementFactory.make("videoscale")
        assert self.videoscale
        self.add(self.videoscale)

        # Use hardware acceleration if present
        # Otherwise can soft flip feeds when / if needed
        # videoflip_method = self.parent.usc.imager.videoflip_method()
        # videoflip_method = self.ac.microscope.usc.imager.videoflip_method()
        videoflip_method = False
        if videoflip_method:
            self.videoflip = Gst.ElementFactory.make("videoflip")
            assert self.videoflip
            self.videoflip.set_property("method", videoflip_method)
            self.add(self.videoflip)

        self.capsfilter = Gst.ElementFactory.make("capsfilter")
        self.add(self.capsfilter)

        self.videoconvert = Gst.ElementFactory.make("videoconvert")
        self.add(self.videoconvert)

        self.openh264enc = Gst.ElementFactory.make("openh264enc")
        assert self.openh264enc
        self.add(self.openh264enc)
        self.h264parse = Gst.ElementFactory.make("h264parse")
        assert self.h264parse
        self.add(self.h264parse)

        self.rtph264pay = Gst.ElementFactory.make("rtph264pay")
        assert self.rtph264pay
        # self.rtph264pay.set_property("name", "pay0")
        self.rtph264pay.set_property("pt", 96) # or 97?
        # self.rtph264pay.set_property("config-interval", 1)
        self.add(self.rtph264pay)

        self.webrtc = Gst.ElementFactory.make("webrtcbin")
        assert self.webrtc
        self.add(self.webrtc)

        # Link videocrop's sink to the bin's sink
        bin_sink_pad = Gst.GhostPad.new("sink",
                                        self.videocrop.get_static_pad("sink"))
        bin_sink_pad.set_active(True)
        self.add_pad(bin_sink_pad)

    def gst_link(self):
        if self.videoflip:
            assert self.videocrop.link(self.videoflip)
            assert self.videoflip.link(self.videoscale)
        else:
            assert self.videocrop.link(self.videoscale)

        assert self.videoscale.link(self.capsfilter)
        assert self.capsfilter.link(self.videoconvert)
        assert self.videoconvert.link(self.openh264enc)
        assert self.openh264enc.link(self.h264parse)
        assert self.h264parse.link(self.rtph264pay)
        assert self.rtph264pay.link(self.webrtc)


class WebRTCClient(Thread):

    webRtcBinReady = pyqtSignal(object)

    def __init__(self, peer_id, binReadycb):
        super().__init__()
        self._id = random.randrange(10, 10000)
        self.binReadycb = binReadycb
        self.ws = None
        self.pipe = None
        self.webrtc = None
        self.peer_id = peer_id
        server = "wss://127.0.0.1:8443"
        self.server = server or STUN_SERVER
        self.sslctx = False
        if self.server.startswith(('wss://', 'https://')):
            self.sslctx = ssl.create_default_context()
            self.sslctx.check_hostname = False
            self.sslctx.verify_mode = ssl.CERT_NONE

    def connect_to_peer(self, peer_id):
        """Establish new connection with peer"""
        self.peer_id = None
        self.stop()
        self.peer_id = peer_id

    def run(self) -> None:
        while True:
            if self.peer_id is not None:
                try:
                    self.loop = asyncio.new_event_loop()
                    self.loop.run_until_complete(self.init_connection())
                    self.loop.run_until_complete(self.message_handler())
                except websockets.ConnectionClosed as e:
                    self.peer_id = None
                except Exception as e:
                    self.peer_id = None
            time.sleep(1)

    async def init_connection(self):
        self.ws = await websockets.connect(self.server, ssl=self.sslctx)
        print("Webrtc client init myid:", self._id)
        await self.ws.send(f'HELLO {self._id}')

    async def setup_call(self):
        await self.ws.send(f'SESSION {self.peer_id}')

    def send_sdp_offer(self, offer):
        text = offer.sdp.as_text()
        # print('Sending offer:\n%s' % text)
        # print("Sending offer...")
        msg = json.dumps({'sdp': {'type': 'offer', 'sdp': text}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.ws.send(msg))

    def on_offer_created(self, promise, _, __):
        promise.wait()
        reply = promise.get_reply()
        offer = reply['offer']
        promise = Gst.Promise.new()
        self.webrtc.emit('set-local-description', offer, promise)
        promise.interrupt()
        self.send_sdp_offer(offer)

    def on_negotiation_needed(self, element):
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, element, None)
        element.emit('create-offer', None, promise)

    def send_ice_candidate_message(self, _, mlineindex, candidate):
        icemsg = json.dumps({'ice': {'candidate': candidate, 'sdpMLineIndex': mlineindex}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.ws.send(icemsg))

    def on_incoming_decodebin_stream(self, _, pad):
        if not pad.has_current_caps():
            # print (pad, 'has no caps, ignoring')
            return
        caps = pad.get_current_caps()
        assert (len(caps))
        s = caps[0]
        name = s.get_name()
        if name.startswith('video'):
            q = Gst.ElementFactory.make('queue')
            conv = Gst.ElementFactory.make('videoconvert')
            sink = Gst.ElementFactory.make('autovideosink')
            self.mywebrtc.add(q, conv, sink)
            self.mywebrtc.sync_children_states()
            pad.link(q.get_static_pad('sink'))
            q.link(conv)
            conv.link(sink)
        elif name.startswith('audio'):
            q = Gst.ElementFactory.make('queue')
            conv = Gst.ElementFactory.make('audioconvert')
            resample = Gst.ElementFactory.make('audioresample')
            sink = Gst.ElementFactory.make('autoaudiosink')
            self.pipe.add(q, conv, resample, sink)
            self.pipe.sync_children_states()
            pad.link(q.get_static_pad('sink'))
            q.link(conv)
            conv.link(resample)
            resample.link(sink)

    def on_incoming_stream(self, _, pad):
        if pad.direction != Gst.PadDirection.SRC:
            return
        # decodebin = Gst.ElementFactory.make('decodebin')
        # # decodebin.connect('pad-added', self.on_incoming_decodebin_stream)
        # self.pipe.add(decodebin)
        # decodebin.sync_state_with_parent()
        # self.webrtc.link(decodebin)

    def init_webrtc_bin(self):
        self.mywebrtc = MyWebRtcBin(gst_element_name="webrtcbin")
        self.mywebrtc.create_elements()
        self.mywebrtc.gst_link()

        # Prepare WebRTCBin
        self.webrtc = self.mywebrtc.webrtc
        self.webrtc.set_property("stun-server", STUN_SERVER)
        self.webrtc.set_property("bundle-policy", "max-bundle")
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.send_ice_candidate_message)
        # self.webrtc.connect('pad-added', self.on_incoming_stream)

        # Only want to send data, not receive
        caps = Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=VP8,payload=96")
        self.webrtc.emit('add-transceiver', GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY, caps)
        trans = self.webrtc.emit('get-transceiver', 0)
        trans.direction = GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY

        self.binReadycb(self.mywebrtc)

    async def handle_sdp(self, message):
        if not message:
            return
        assert (self.webrtc)
        msg = json.loads(message)
        if 'sdp' in msg:
            sdp = msg['sdp']
            assert(sdp['type'] == 'answer')
            sdp = sdp['sdp']
            # print("---")
            # print('Received answer:\n%s' % sdp)
            # print("Received answer")
            res, sdpmsg = GstSdp.SDPMessage.new()
            GstSdp.sdp_message_parse_buffer(bytes(sdp.encode()), sdpmsg)
            answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
            promise = Gst.Promise.new()
            self.webrtc.emit('set-remote-description', answer, promise)
            promise.interrupt()
        elif 'ice' in msg:
            ice = msg['ice']
            candidate = ice['candidate']
            sdpmlineindex = ice['sdpMLineIndex']
            self.webrtc.emit('add-ice-candidate', sdpmlineindex, candidate)

    async def message_handler(self):
        assert self.ws
        try:
            async for message in self.ws:
                if message == 'HELLO':
                    await self.setup_call()
                elif message == 'SESSION_OK':
                    self.init_webrtc_bin()
                elif message.startswith('ERROR'):
                    raise Exception(message)
                else:
                    await self.handle_sdp(message)
        except Exception as e:
            await self.stop()
            raise Exception(e)
        

    async def stop(self):
        await self.ws.close()
        await self.loop.stop()
        self.ws = None
        self.loop = None
        self.peer_id = None

def check_plugins():
    needed = ["opus", "vpx", "webrtc", "dtls", "srtp", "rtp",
              "rtpmanager", "videotestsrc", "audiotestsrc"]  # removed nice
    missing = list(filter(lambda p: Gst.Registry.get().find_plugin(p) is None, needed))
    if len(missing):
        print('Missing gstreamer plugins:', missing)
        return False
    return True

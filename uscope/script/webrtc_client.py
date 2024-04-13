"""

"""
import random
import websockets
import asyncio
import json
import gi
import ssl
import time
from threading import Thread, Event
gi.require_version('Gst', '1.0')
from gi.repository import Gst
gi.require_version('GstWebRTC', '1.0')
from gi.repository import GstWebRTC
gi.require_version('GstSdp', '1.0')
from gi.repository import GstSdp

STUN_SERVER = "stun://stun.l.google.com:19302"


ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
localhost_pem = "uscope/script/assets/localhost.pem"
ssl_context.load_verify_locations(localhost_pem)

Gst.init(None)


class WebRtcPipe(Gst.Pipeline):

    port = 8554
    def __init__(
        self,
        gst_element_name=None,
        incoming_wh=None,
    ):
        super().__init__()

        # self.player = player
        self.gst_element_name = gst_element_name

        self.updsrc = None
        self.videocrop = None
        # Used to fit incoming stream to window
        self.videoscale = None
        # Tell the videoscale the window size we need
        self.capsfilter = None
        #
        self.videoflip = None

        # H264 to RTP to WebRTC
        self.videoconvert = None
        self.openh264enc = None
        self.h264parse = None
        self.rtph264pay = None

    def create_elements(self):
        self.udpsrc = Gst.ElementFactory.make("udpsrc")
        assert self.udpsrc
        self.udpsrc.set_property("name", "pay0")
        self.udpsrc.set_property("port", self.port)

        def create_caps():
            caps = Gst.Caps.new_empty_simple("application/x-rtp")
            caps.set_value("media", "video")
            caps.set_value("buffer-size", 524288)
            caps.set_value("clock-rate", 90000)
            caps.set_value("encoding-name", "H264")
            caps.set_value("payload", 96)
            return caps

        self.udpsrc.set_property("caps", create_caps())
        self.add(self.udpsrc)

        self.capsfilter = Gst.ElementFactory.make("capsfilter")
        self.add(self.capsfilter)

        # self.openh264enc = Gst.ElementFactory.make("openh264enc")
        # assert self.openh264enc
        # self.add(self.openh264enc)

        # self.h264parse = Gst.ElementFactory.make("h264parse")
        # assert self.h264parse
        # self.add(self.h264parse)

        self.rtph264depay = Gst.ElementFactory.make("rtph264depay")
        assert self.rtph264depay
        self.add(self.rtph264depay)
    
        self.rtph264pay = Gst.ElementFactory.make("rtph264pay")
        assert self.rtph264pay
        self.rtph264pay.set_property("pt", 96)
        self.rtph264pay.set_property("config-interval", 1)
        self.add(self.rtph264pay)

        self.queue = Gst.ElementFactory.make("queue")
        self.add(self.queue)

    def gst_link(self):
        assert self.udpsrc.link(self.capsfilter)
        assert self.capsfilter.link(self.rtph264depay)
        # assert self.openh264enc.link(self.h264parse)
        # assert self.h264parse.link(self.rtph264depay)
        assert self.rtph264depay.link(self.rtph264pay)
        assert self.rtph264pay.link(self.queue)


class WebRTCClient(Thread):

    def __init__(self):
        super().__init__()
        self._id = random.randrange(10, 10000)
        self._connections = {}
        self._conn_requests = set()
        self.loop = asyncio.new_event_loop()
        self.pipe = None
        self.ws = None
        server = "wss://127.0.0.1:8443"
        self.server = server or STUN_SERVER

    def run(self):
        self.stopEvent = Event()
        self.stopEvent.set()
        self.loop.run_until_complete(self.connect())
        while self.stopEvent.is_set():
            
            time.sleep(1)

    async def connect(self):
        async with websockets.connect(self.server, ssl=ssl_context) as self.ws:
            await self.ws.send(f'HELLO {self._id}') # Register with server
            self.loop.create_task(self.connection_handler())
            while True:
                # For any peer request, establish a session
                if self._conn_requests:
                    peer_id = self._conn_requests.pop()
                    if peer_id:
                        self.loop.create_task(self.setup_call(peer_id))
                await asyncio.sleep(1)

    def add_peer_connection(self, peer_id):
        """Establish WebRTC session with peer"""
        self._conn_requests.add(peer_id)

    async def setup_call(self, peer_id):
        await self.ws.send(f'SESSION {peer_id}')

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

    def on_incoming_stream(self, _, pad):
        if pad.direction != Gst.PadDirection.SRC:
            return

    def init_webrtc_bin(self, peer_id):
        if not self.pipe:
            self.pipe = WebRtcPipe(gst_element_name="webrtc")
            self.pipe.create_elements()
            self.pipe.gst_link()

        webrtcbin = Gst.ElementFactory.make("webrtcbin")
        assert webrtcbin
        self.pipe.add(webrtcbin)
        webrtcbin.set_property("stun-server", STUN_SERVER)
        webrtcbin.set_property("bundle-policy", "max-bundle")
        webrtcbin.connect('on-negotiation-needed', self.on_negotiation_needed)
        webrtcbin.connect('on-ice-candidate', self.send_ice_candidate_message)
        # webrtcbin.connect('pad-added', self.on_incoming_stream)

        # Only want to send data, not receive
        caps = Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=VP8,payload=96")
        webrtcbin.emit('add-transceiver', GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY, caps)
        trans = webrtcbin.emit('get-transceiver', 0)
        trans.direction = GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY

        self._connections[peer_id] = webrtcbin
        print(self._connections)
        self.pipe.add(webrtcbin)
        self.pipe.queue.link(webrtcbin)
        self.pipe.set_state(Gst.State.PLAYING)

    async def handle_sdp(self, message):
        assert (self.webrtc)
        msg = json.loads(message)
        if 'sdp' in msg:
            sdp = msg['sdp']
            assert(sdp['type'] == 'answer')
            sdp = sdp['sdp']
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

    async def connection_handler(self):
        assert self.ws
        async for msg in self.ws:
            if msg is None:
                break
            if msg == 'HELLO':
                pass  # Registered
                # await self.setup_call()
            elif msg.startswith('SESSION_OK'):
                _, peer_id = msg.split(maxsplit=1)
                # print(f"Session established with %peer_id")
                self.init_webrtc_bin(peer_id)
            elif msg.startswith('ERROR'):
                self.peer_id = None
                pass
            else:
                await self.handle_sdp(msg)

    def shutdown(self, cb=None):
        self.stopEvent.clear()
        self.peer_id = None
        self.loop.stop()
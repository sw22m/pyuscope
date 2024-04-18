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

    host = "127.0.0.1"
    port = 8554
    def __init__(
        self,
        gst_element_name=None,
        incoming_wh=None,
    ):
        super().__init__()
        self.gst_element_name = gst_element_name

        self.updsrc = None
        # H264 to RTP to WebRTC
        self.videoconvert = None
        self.openh264enc = None
        self.h264parse = None
        self.rtph264pay = None

    def create_elements(self):
        self.udpsrc = Gst.ElementFactory.make("udpsrc")
        assert self.udpsrc
        self.udpsrc.set_property("name", "pay0")
        self.udpsrc.set_property("address", WebRtcPipe.host)
        self.udpsrc.set_property("port", WebRtcPipe.port)

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

        self.rtpjitterbuffer = Gst.ElementFactory.make("rtpjitterbuffer")
        assert self.rtpjitterbuffer
        self.add(self.rtpjitterbuffer)

        self.rtph264depay = Gst.ElementFactory.make("rtph264depay")
        assert self.rtph264depay
        self.add(self.rtph264depay)

        self.h264parse = Gst.ElementFactory.make("h264parse")
        assert self.h264parse
        self.add(self.h264parse)

        self.rtph264pay = Gst.ElementFactory.make("rtph264pay")
        assert self.rtph264pay
        self.add(self.rtph264pay)
        self.rtph264pay.set_property("name", "pay0")
        self.rtph264pay.set_property("pt", 96)
        self.rtph264pay.set_property("config-interval", 1)

        # self.rtpjitterbuffer = Gst.ElementFactory.make("rtpjitterbuffer")
        # assert self.rtpjitterbuffer
        # self.add(self.rtpjitterbuffer)
        self.queue2 = Gst.ElementFactory.make("queue")
        self.add(self.queue2)

    def gst_link(self):
        assert self.udpsrc.link(self.rtpjitterbuffer)
        assert self.rtpjitterbuffer.link(self.rtph264depay)
        assert self.rtph264depay.link(self.h264parse)
        assert self.h264parse.link(self.rtph264pay)
        # assert self.rtph264depay.link(self.h264enc)
        # assert self.h264parse.link(self.rtpjitterbuffer)
        pass

    def add_webrtcbin(self, webrtcbin):
        queue = Gst.ElementFactory.make("queue")
        self.add(queue)
        self.rtph264pay.link(queue)
        self.add(webrtcbin)
        assert queue.link(webrtcbin)

        return
        queue = Gst.ElementFactory.make("queue")
        try:
            self.add(queue)
            assert self.tee.link(queue)
        except:
            pass

        try:
            self.add(bin)
            assert queue.link(bin)
        except:
            raise


class WebRtcBin:

    def __init__(self, ws, peer_id):
        self.ws = ws
        self.peer_id = peer_id
        self.bin = Gst.ElementFactory.make("webrtcbin")
        # self.bin.set_property("stun-server", STUN_SERVER)
        self.bin.set_property("bundle-policy", "max-bundle")
        self.bin.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.bin.connect('on-ice-candidate', self.send_ice_candidate_message)

        # Only want to send data, not receive
        def create_caps():
            caps = Gst.Caps.new_empty_simple("application/x-rtp")
            caps.set_value("media", "video")
            caps.set_value("buffer-size", 524288)
            caps.set_value("clock-rate", 90000)
            caps.set_value("encoding-name", "H264")
            caps.set_value("payload", 96)
            return caps
        self.bin.emit('add-transceiver', GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY, create_caps())
        trans = self.bin.emit('get-transceiver', 0)
        trans.direction = GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY

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
        self.bin.emit('set-local-description', offer, promise)
        promise.interrupt()
        self.send_sdp_offer(offer)

    def on_negotiation_needed(self, element):
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, element, None)
        element.emit('create-offer', None, promise)

    def send_ice_candidate_message(self, _, mlineindex, candidate):
        icemsg = json.dumps({'ice': {'candidate': candidate, 'sdpMLineIndex': mlineindex}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.ws.send(icemsg))
    
    async def handle_sdp(self, message):
        print(message, 2212122)
        assert (self.bin)
        msg = json.loads(message)
        if 'sdp' in msg:
            sdp = msg['sdp']
            assert(sdp['type'] == 'answer')
            sdp = sdp['sdp']
            res, sdpmsg = GstSdp.SDPMessage.new()
            GstSdp.sdp_message_parse_buffer(bytes(sdp.encode()), sdpmsg)
            answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
            promise = Gst.Promise.new()
            self.bin.emit('set-remote-description', answer, promise)
            promise.interrupt()
        elif 'ice' in msg:
            ice = msg['ice']
            candidate = ice['candidate']
            sdpmlineindex = ice['sdpMLineIndex']
            self.bin.emit('add-ice-candidate', sdpmlineindex, candidate)


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

    def init_webrtc_bin(self, peer_id):
        if not self.pipe:
            self.pipe = WebRtcPipe(gst_element_name="webrtc")
            self.pipe.create_elements()
            self.pipe.gst_link()

        webrtcbin = WebRtcBin(self.ws, peer_id)
        assert webrtcbin.bin

        self._connections[peer_id] = webrtcbin
        self.pipe.add_webrtcbin(webrtcbin.bin)
        self.webrtcbin = webrtcbin
        self.pipe.set_state(Gst.State.PLAYING)
    
    async def connection_handler(self):
        assert self.ws
        async for msg in self.ws:
            print(msg)
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
                await self.webrtcbin.handle_sdp(msg)

    def shutdown(self, cb=None):
        self.stopEvent.clear()
        self.peer_id = None
        self.loop.stop()
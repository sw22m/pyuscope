"""
Ubuntu 20.04 setup:
sudo apt-get install -y python3-werkzeug
sudo pip3 install Flask>=2.2.2

Fixes:
<class 'ImportError'>: cannot import name 'escape' from 'jinja2' (/usr/local/lib/python3.8/dist-packages/jinja2/__init__.py)
https://stackoverflow.com/questions/71718167/importerror-cannot-import-name-escape-from-jinja2



Sample commands

# Get this microscope's objective database
$ curl 'http://localhost:8080/get/objectives'; echo

# Get the current objective
$ curl 'http://localhost:8080/get/active_objective'; echo
{"data": {"objective": "5X"}, "status": 200}

# Change to a new objective
$ curl 'http://localhost:8080/set/active_objective/5X'; echo
{"status": 200}
# POST requests also work
$ curl -X POST 'http://localhost:8080/set/active_objective/10X'; echo
# With spaces
$ curl 'http://localhost:8080/set/active_objective/100X%20Oil'; echo
$ curl 'http://localhost:8080/get/active_objective'; echo
{"data": {"objective": "100X Oil"}, "status": 200}
# An invalid value
$ curl 'http://localhost:8080/set/active_objective/1000X'; echo
{"status": 400}

# Get the current position
$ curl 'http://localhost:8080/get/pos'; echo

# Move absolute position
$ curl 'http://localhost:8080/set/pos/?x=1&z=-2'; echo
# Move relative position
$ curl -X POST 'http://localhost:8080/set/pos/?y=1&x=-1&relative=1'; echo
"""
from uscope.gui.scripting import ArgusScriptingPlugin
from uscope.script import webserver_common

import ssl
from flask import Flask, request, current_app, render_template, send_from_directory
from werkzeug.serving import make_server
from flask_cors import CORS
import cv2
import base64
import numpy as np
import websockets
from flask_sock import Sock
from uscope.script.webrtc_client import WebRTCClient

FLUTTER_WEB_DIR = "web"
app = Flask(__name__, template_folder=FLUTTER_WEB_DIR)
# Keep alive and for detecting unresponsive clients
app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 25}
CORS(app)
SERVER_PORT = 8443
HOST = '127.0.0.1'


def image_to_base64(p_img):
    frame = cv2.cvtColor(np.array(p_img), cv2.COLOR_RGB2BGR)
    img_encode = cv2.imencode('.jpg', frame)[1]
    string_data = base64.b64encode(img_encode).decode('utf-8')
    b64_src = ''
    return b64_src + string_data


class SignallingServer(Sock):

    KEEPALIVE_TIMEOUT = 30

    def __init__(self, app = None):
        super().__init__(app=app)
        self.peers: dict = {}
        self.sessions: dict = {}
        self.rooms: dict = {}
        make_socket(self)

    def cleanup_session(self, uid):
        if uid in self.sessions:
            other_id = self.sessions[uid]
            del self.sessions[uid]
            current_app.plugin.log(f"Cleaned up session: {uid}")
            if other_id in self.sessions:
                del self.sessions[other_id]
                current_app.plugin.log(f"Also cleaned up session: {other_id}")
                # If there was a session with this peer, also
                # close the connection to reset its state.
                if other_id in self.peers:
                    current_app.plugin.log(f"Closing connection to {other_id}")
                    wso, oaddr, _ = self.peers[other_id]
                    del self.peers[other_id]
                    wso.close()

    def cleanup_room(self, uid, room_id):
        room_peers = self.rooms[room_id]
        if uid not in room_peers:
            return
        room_peers.remove(uid)
        for pid in room_peers:
            wsp, paddr, _ = self.peers[pid]
            msg = f"ROOM_PEER_LEFT {uid}"
            wsp.send(msg)

    def remove_peer(self, uid):
        self.cleanup_session(uid)
        if uid in self.peers:
            ws, raddr, status = self.peers[uid]
            if status and status != "session":
                self.cleanup_room(uid, status)
            del self.peers[uid]
            ws.close()
            current_app.plugin.log(f"Disconnected from peer {uid} at {raddr}")

def make_socket(sock):

    def get_remote_addr(ws):
        return ws.sock.getpeername()

    @sock.route("/webrtc")
    def webrtc(ws):
        peer_id = ws.receive()
        current_app.plugin.start_webrtc_session(int(peer_id))

    @sock.route("/")
    def handler(ws):
        """All connections start from here"""
        peer_id = hello_peer(ws) # Wait for connected client to register
        if peer_id is None:
            return
        # if request.environ.get("HTTP_X_FORWARDED_FOR") is None:
        #     print(request.environ["REMOTE_ADDR"])
        # else:
        #     print(request.environ["HTTP_X_FORWARDED_FOR"]) # if behind a proxy
        try:
            # Registered peer, now continue to listen
            connection_handler(ws, peer_id)
        except websockets.ConnectionClosed:
            raddr = get_remote_addr(ws)
            current_app.plugin.log(f"Connection to peer {raddr} closed, exiting handler")
        except Exception as e:
            pass
        finally:
            sock.remove_peer(peer_id)

    def hello_peer(ws):
        """Client registers as a peer by sending `HELLO <uid>`"""
        try:
            # print('Websocket connected', ws, ' - ')
            message = ws.receive()
            hello, uid = message.split(maxsplit=1)
            # print('message received', hello, uid)
            if hello != "HELLO":
                ws.close(reason="invalid protocol")
                return None
            if not uid or uid.split() != [uid]: # no whitespace
                ws.close(reason=f"invalid peer: `{uid}`")
            if uid in sock.peers:
                ws.close(reason=f"Peer already exists: {uid}")
            ws.send("HELLO")  # Acknowledge the peer
            return uid
        except websockets.ConnectionClosed as e:
            ws.close()
        return None

    def connection_handler(ws, uid):
        raddr = get_remote_addr(ws)
        peer_status = None
        sock.peers[uid] = [ws, raddr, peer_status]
        current_app.plugin.log(f"Registered peer {uid} at {raddr}")
        while True:
            # Receive command, wait forever if necessary
            msg = ws.receive(timeout=SignallingServer.KEEPALIVE_TIMEOUT)
            # Update current status
            peer_status = sock.peers[uid][2]
            # We are in a session or a room, messages must be relayed
            if peer_status is not None:
                # We"re in a session, route message to connected peer
                if peer_status == "session":
                    other_id = sock.sessions[uid]
                    wso, oaddr, status = sock.peers[other_id]
                    assert(status == "session")
                    wso.send(msg)
                # We"re in a room, accept room-specific commands
                elif peer_status:
                    # ROOM_PEER_MSG peer_id MSG
                    if msg.startswith("ROOM_PEER_MSG"):
                        _, other_id, msg = msg.split(maxsplit=2)
                        if other_id not in sock.peers:
                            ws.send(f"ERROR peer {other_id} not found")
                            continue
                        wso, oaddr, status = sock.peers[other_id]
                        if status != room_id:
                            ws.send(f"ERROR peer {other_id} is not in the room")
                            continue
                        msg = f"ROOM_PEER_MSG {uid} {msg}"
                        current_app.plugin.log(f"room {room_id}: {uid} -> {other_id}: {msg}")
                        wso.send(msg)
                    elif msg == "ROOM_PEER_LIST":
                        _, peer_id = msg.split(maxsplit=2)
                        room_id = sock.peers[peer_id][2]
                        room_peers = " ".join([pid for pid in sock.rooms[room_id] if pid != sock.peer_id])
                        msg = f"ROOM_PEER_LIST {room_peers}"
                        current_app.plugin.log(f"room {room_id}: -> {uid}: {msg}")
                        ws.send(msg)
                    else:
                        ws.send("ERROR invalid msg, already in room")
                        continue
                else:
                    raise AssertionError(f"Unknown peer status {peer_status}")
            # Requested a session with a specific peer
            elif msg.startswith("SESSION"):
                current_app.plugin.log(f"Command from {uid}: {msg}")
                _, callee_id = msg.split(maxsplit=1)
                if callee_id not in sock.peers:
                    ws.send(f"ERROR peer {callee_id} not found")
                    continue
                if peer_status is not None:
                    ws.send(f"ERROR peer {callee_id} busy")
                    continue
                ws.send(f"SESSION_OK {callee_id}")
                wsc = sock.peers[callee_id][0]
                current_app.plugin.log(f"Session from peer {uid} ({raddr}) to peer {callee_id} ({get_remote_addr(wsc)})")
                # Register session
                sock.peers[uid][2] = peer_status = "session"
                sock.sessions[uid] = callee_id
                sock.peers[callee_id][2] = "session"
                sock.sessions[callee_id] = uid
            # Requested joining or creation of a room
            elif msg.startswith("ROOM"):
                current_app.plugin.log(f"{uid} command {msg}")
                _, room_id = msg.split(maxsplit=1)
                # Room name cannot be "session", empty, or contain whitespace
                if room_id == "session" or room_id.split() != [room_id]:
                    ws.send(f"ERROR invalid room id {room_id}")
                    continue
                # Create room if it doesn't exist
                sock.rooms.setdefault(room_id, set())
                if uid in sock.rooms[room_id]:
                    raise AssertionError("Should not receive ROOM command current member")
                room_peers = " ".join([pid for pid in sock.rooms[room_id]])
                ws.send(f"ROOM_OK {room_peers}")
                # Enter room
                sock.peers[uid][2] = peer_status = room_id
                sock.rooms[room_id].add(uid)
                for pid in sock.rooms[room_id]:
                    if pid == uid:
                        continue
                    wsp, paddr, _ = sock.peers[pid]
                    msg = f"ROOM_PEER_JOINED {uid}"
                    current_app.plugin.log(f"room {room_id}: {uid} -> {pid}: {msg}")
                    wsp.send(msg)
            else:
                current_app.plugin.log(f"Ignoring unknown message {msg} from {uid}")


class Plugin(ArgusScriptingPlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.verbose = True
        self.frame = None
        self.socket = None
        self.webrtc_client = None

    def log_verbose(self, msg):
        if self.verbose:
            self.log(msg)

    def run_test(self):
        self.log(f"Running Pyuscope Webserver Plugin on port: {SERVER_PORT}")
        self.objectives = self._ac.microscope.get_objectives()
        if not self.socket:
            self.socket = SignallingServer(app)

        # Keep a reference to this plugin
        app.plugin = self

        # Cert chain
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # localhost_pem = pathlib.Path(__file__).with_name("assets/localhost.pem")
        localhost_pem = "uscope/script/assets/localhost.pem"
        ssl_context.load_cert_chain(localhost_pem)
        # cert_path = "uscope/script/assets/cert.pem"
        # cert_key_path = "uscope/script/assets/cert-key.pem"
        # if not os.path.exists(cert_path) or not os.path.exists(cert_key_path):
        #     raise Warning("SSL Certificate not found required for WebRTC communication")
        # ssl_context=(cert_path, cert_key_path)
        self.server = make_server(host=HOST,
                                  port=SERVER_PORT,
                                  app=app,
                                  threaded=True,
                                  ssl_context=ssl_context)
        self.ctx = app.app_context()
        self.ctx.push()
        self.server.serve_forever(0.1)

    def shutdown(self):
        if self.webrtc_client:
            self.webrtc_client.shutdown()
            self.webrtc_client = None
        self.server.shutdown()
        self.server.server_close()
        super().shutdown()
        self.server = None

    def start_webrtc_session(self, peer_id):
        self.enable_udp_sink()
        if not self.webrtc_client:
            self.webrtc_client = WebRTCClient()
            self.webrtc_client.start()
        self.webrtc_client.add_peer_connection(peer_id)


webserver_common.make_app(app)


@app.route('/')
@app.route('/index.html')
def index():
    return render_template('index.html')


@app.route('/<path:name>')
def return_flutter_doc(name):
    """
    Required to serve flutter web docs
    """
    data_list = str(name).split('/')
    dir_name = FLUTTER_WEB_DIR
    if len(data_list) > 1:
        for i in range(0, len(data_list) - 1):
            dir_name += '/' + data_list[i]
    return send_from_directory(dir_name, data_list[-1])

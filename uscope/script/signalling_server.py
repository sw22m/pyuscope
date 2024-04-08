import websockets
import asyncio
import traceback
from .webrtc_client import run

KEEPALIVE_TIMEOUT = 30

class SignallingServer:

    def __init__(self, host="localhost", port=8080) -> None:
        self.host = host
        self.port = port
        self.peers: dict = {}
        self.sessions: dict = {}
        self.rooms: dict = {}

    async def recv_msg_ping(self, ws, raddr):
        """
        Wait for a message forever, and send a regular ping to prevent bad routers
        from closing the connection.
        """
        msg = None
        while msg is None:
            try:
                msg = await asyncio.wait_for(ws.recv(), KEEPALIVE_TIMEOUT)
            except asyncio.exceptions.TimeoutError:
                print('Sending keepalive ping to {!r} in recv'.format(raddr))
                await ws.ping()
        return msg

    async def disconnect(self, ws, peer_id):
        """
        Remove @peer_id from the list of sessions and close our connection to it.
        This informs the peer that the session and all calls have ended, and it
        must reconnect.
        """
        if peer_id in self.sessions:
            del self.sessions[peer_id]
        # Close connection
        if ws and ws.open:
            # Don't care about errors
            asyncio.ensure_future(ws.close(reason='hangup'))

    async def cleanup_session(self, uid):
        if uid in self.sessions:
            other_id = self.sessions[uid]
            del self.sessions[uid]
            print("Cleaned up {} session".format(uid))
            if other_id in self.sessions:
                del self.sessions[other_id]
                print("Also cleaned up {} session".format(other_id))
                # If there was a session with this peer, also
                # close the connection to reset its state.
                if other_id in self.peers:
                    print("Closing connection to {}".format(other_id))
                    wso, oaddr, _ = self.peers[other_id]
                    del self.peers[other_id]
                    await wso.close()

    async def cleanup_room(self, uid, room_id):
        room_peers = self.rooms[room_id]
        if uid not in room_peers:
            return
        room_peers.remove(uid)
        for pid in room_peers:
            wsp, paddr, _ = self.peers[pid]
            msg = 'ROOM_PEER_LEFT {}'.format(uid)
            print('room {}: {} -> {}: {}'.format(room_id, uid, pid, msg))
            await wsp.send(msg)

    async def remove_peer(self, uid):
        await self.cleanup_session(uid)
        if uid in self.peers:
            ws, raddr, status = self.peers[uid]
            if status and status != 'session':
                await self.cleanup_room(uid, status)
            del self.peers[uid]
            await ws.close()
            print("Disconnected from peer {!r} at {!r}".format(uid, raddr))

    async def connection_handler(self, ws, uid):
        raddr = ws.remote_address
        peer_status = None
        self.peers[uid] = [ws, raddr, peer_status]
        print("Registered peer {!r} at {!r}".format(uid, raddr))
        while True:
            # Receive command, wait forever if necessary
            msg = await self.recv_msg_ping(ws, raddr)
            # Update current status
            peer_status = self.peers[uid][2]
            # We are in a session or a room, messages must be relayed
            if peer_status is not None:
                # We're in a session, route message to connected peer
                if peer_status == 'session':
                    other_id = self.sessions[uid]
                    wso, oaddr, status = self.peers[other_id]
                    assert(status == 'session')
                    print("{} -> {}: {}".format(uid, other_id, msg))
                    await wso.send(msg)
                # We're in a room, accept room-specific commands
                elif peer_status:
                    # ROOM_PEER_MSG peer_id MSG
                    if msg.startswith('ROOM_PEER_MSG'):
                        _, other_id, msg = msg.split(maxsplit=2)
                        if other_id not in self.peers:
                            await ws.send('ERROR peer {!r} not found'
                                        ''.format(other_id))
                            continue
                        wso, oaddr, status = self.peers[other_id]
                        if status != room_id:
                            await ws.send('ERROR peer {!r} is not in the room'
                                        ''.format(other_id))
                            continue
                        msg = 'ROOM_PEER_MSG {} {}'.format(uid, msg)
                        print('room {}: {} -> {}: {}'.format(room_id, uid, other_id, msg))
                        await wso.send(msg)
                    elif msg == 'ROOM_PEER_LIST':
                        room_id = self.peers[peer_id][2]
                        room_peers = ' '.join([pid for pid in self.rooms[room_id] if pid != self.peer_id])
                        msg = 'ROOM_PEER_LIST {}'.format(room_peers)
                        print('room {}: -> {}: {}'.format(room_id, uid, msg))
                        await ws.send(msg)
                    else:
                        await ws.send('ERROR invalid msg, already in room')
                        continue
                else:
                    raise AssertionError('Unknown peer status {!r}'.format(peer_status))
            # Requested a session with a specific peer
            elif msg.startswith('SESSION'):
                print("{!r} command {!r}".format(uid, msg))
                _, callee_id = msg.split(maxsplit=1)
                if callee_id not in self.peers:
                    await ws.send('ERROR peer {!r} not found'.format(callee_id))
                    continue
                if peer_status is not None:
                    await ws.send('ERROR peer {!r} busy'.format(callee_id))
                    continue
                await ws.send('SESSION_OK')
                wsc = self.peers[callee_id][0]
                print(f'Session from {uid} ({raddr}) to {callee_id} ({wsc.remote_address})')
                # Register session
                self.peers[uid][2] = peer_status = 'session'
                self.sessions[uid] = callee_id
                self.peers[callee_id][2] = 'session'
                self.sessions[callee_id] = uid
            # Requested joining or creation of a room
            elif msg.startswith('ROOM'):
                print('{!r} command {!r}'.format(uid, msg))
                _, room_id = msg.split(maxsplit=1)
                # Room name cannot be 'session', empty, or contain whitespace
                if room_id == 'session' or room_id.split() != [room_id]:
                    await ws.send('ERROR invalid room id {!r}'.format(room_id))
                    continue
                if room_id in self.rooms:
                    if uid in self.rooms[room_id]:
                        raise AssertionError('How did we accept a ROOM command '
                                            'despite already being in a room?')
                else:
                    # Create room if required
                    self.rooms[room_id] = set()
                room_peers = ' '.join([pid for pid in self.rooms[room_id]])
                await ws.send('ROOM_OK {}'.format(room_peers))
                # Enter room
                self.peers[uid][2] = peer_status = room_id
                self.rooms[room_id].add(uid)
                for pid in self.rooms[room_id]:
                    if pid == uid:
                        continue
                    wsp, paddr, _ = self.peers[pid]
                    msg = 'ROOM_PEER_JOINED {}'.format(uid)
                    print('room {}: {} -> {}: {}'.format(room_id, uid, pid, msg))
                    await wsp.send(msg)
            else:
                print('Ignoring unknown message {!r} from {!r}'.format(msg, uid))

    # Client can register itself as a peer by sending `HELLO` with a uid e.g. `HELLO 123` 
    async def hello_peer(self, ws) -> int:
        print("A client just connected", ws.remote_address, ws)
        try:
            message = await ws.recv()
            hello, uid = message.split(maxsplit=1)
            if hello != "HELLO":
                await ws.close(code=1002, reason='invalid protocol') # Invalid HELLO command
                return
            if not uid or uid in self.peers or uid.split() != [uid]: # no whitespace
                await ws.close(code=1002, reason='invalid peer uid')
            await ws.send("HELLO")  # Acknowledge the peer
            return uid
        except websockets.exceptions.ConnectionClosed as e:
            print("A client just disconnected")

    async def handler(self, ws):
        """All incoming messages are handled here"""
        raddr = ws.remote_address
        print("Connected to {!r}".format(raddr))
        peer_id = await self.hello_peer(ws)
        try:
            # Registered peer, now continue to listen
            await self.connection_handler(ws, peer_id)
        except websockets.ConnectionClosed:
            print("Connection to peer {!r} closed, exiting handler".format(raddr))
        except:
            traceback.print_exc()
        finally:
            await self.remove_peer(peer_id)

    def serve(self):
        start_server = websockets.serve(self.handler, self.host, self.port)
        asyncio.get_event_loop().run_until_complete(start_server)
        asyncio.get_event_loop().run_forever()
    

if __name__ == "__main__":
    server = SignallingServer()
    server.serve()

#!/usr/bin/python

"""
UDP Communications Module
"""

import asyncio
import socket
import pickle
import queue

from time import time as _time

from .debugging import ModuleLogger, bacpypes_debugging

from .core import deferred
from .task import FunctionTask
from .comm import PDU, Server
from .comm import ServiceAccessPoint

# some debugging
_debug = 0
_log = ModuleLogger(globals())

#
#   UDPActor
#
#   Actors are helper objects for a director.  There is one actor for
#   each peer.
#

@bacpypes_debugging
class UDPActor:

    def __init__(self, director, peer):
        if _debug: UDPActor._debug("__init__ %r %r", director, peer)

        # keep track of the director
        self.director = director

        # associated with a peer
        self.peer = peer

        # add a timer
        self.timeout = director.timeout
        if self.timeout > 0:
            self.timer = FunctionTask(self.idle_timeout)
            self.timer.install_task(_time() + self.timeout)
        else:
            self.timer = None

        # tell the director this is a new actor
        self.director.add_actor(self)

    def idle_timeout(self):
        if _debug: UDPActor._debug("idle_timeout")

        # tell the director this is gone
        self.director.del_actor(self)

    def indication(self, pdu):
        if _debug: UDPActor._debug("indication %r", pdu)

        # reschedule the timer
        if self.timer:
            self.timer.install_task(_time() + self.timeout)

        # put it in the outbound queue for the director
        self.director.request.put(pdu)

    def response(self, pdu):
        if _debug: UDPActor._debug("response %r", pdu)

        # reschedule the timer
        if self.timer:
            self.timer.install_task(_time() + self.timeout)

        # process this as a response from the director
        self.director.response(pdu)

    def handle_error(self, error=None):
        if _debug: UDPActor._debug("handle_error %r", error)

        # pass along to the director
        if error is not None:
            self.director.actor_error(self, error)

#
#   UDPPickleActor
#

@bacpypes_debugging
@bacpypes_debugging
class UDPDirectorProtocol(asyncio.DatagramProtocol):
    def __init__(self, director):
        if _debug: UDPDirectorProtocol._debug("__init__ %r", director)
        self.director = director

    def connection_made(self, transport):
        if _debug: UDPDirectorProtocol._debug("connection_made %r", transport)
        self.director.transport = transport

    def datagram_received(self, data, addr):
        if _debug: UDPDirectorProtocol._debug("datagram_received %d octets from %r", len(data), addr)
        deferred(self.director.response, PDU(data, source=addr))

    def error_received(self, exc):
        if _debug: UDPDirectorProtocol._debug("error_received %r", exc)
        self.director.handle_error(exc)

    def connection_lost(self, exc):
        if _debug: UDPDirectorProtocol._debug("connection_lost %r", exc)
        if exc:
            self.director.handle_error(exc)

class UDPPickleActor(UDPActor):

    def __init__(self, *args):
        if _debug: UDPPickleActor._debug("__init__ %r", args)
        UDPActor.__init__(self, *args)

    def indication(self, pdu):
        if _debug: UDPPickleActor._debug("indication %r", pdu)

        # pickle the data
        pdu.pduData = pickle.dumps(pdu.pduData)

        # continue as usual
        UDPActor.indication(self, pdu)

    def response(self, pdu):
        if _debug: UDPPickleActor._debug("response %r", pdu)

        # unpickle the data
        try:
            pdu.pduData = pickle.loads(pdu.pduData)
        except:
            UDPPickleActor._exception("pickle error")
            return

        # continue as usual
        UDPActor.response(self, pdu)

#
#   UDPDirector
#

@bacpypes_debugging
class UDPDirector(Server, ServiceAccessPoint):

    def __init__(self, address, timeout=0, reuse=False, actorClass=UDPActor, sid=None, sapID=None):
        if _debug: UDPDirector._debug("__init__ %r timeout=%r reuse=%r actorClass=%r sid=%r sapID=%r", address, timeout, reuse, actorClass, sid, sapID)
        Server.__init__(self, sid)
        ServiceAccessPoint.__init__(self, sapID)

        # check the actor class
        if not issubclass(actorClass, UDPActor):
            raise TypeError("actorClass must be a subclass of UDPActor")
        self.actorClass = actorClass

        # save the timeout for actors
        self.timeout = timeout

        # save the address
        self.address = address

        # create the socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)

        # if the reuse parameter is provided, set the socket option
        if reuse:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # proceed with the bind
        try:
            self.socket.bind(address)
        except socket.error as err:
            if _debug: UDPDirector._debug("    - bind error: %r", err)
            self.socket.close()
            raise
        if _debug: UDPDirector._debug("    - getsockname: %r", self.socket.getsockname())

        # allow it to send broadcasts
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # create the request queue and transport
        self.request = queue.Queue()
        self.transport = None
        self._protocol = None

        # start with an empty peer pool
        self.peers = {}

        # get the event loop and start the protocol
        self.loop = asyncio.get_event_loop()
        self.loop.create_task(self.start_protocol())

    async def start_protocol(self):
        if _debug: UDPDirector._debug("start_protocol")
        try:
            self.transport, self._protocol = await self.loop.create_datagram_endpoint(
                lambda: UDPDirectorProtocol(self),
                sock=self.socket
            )
        except Exception as err:
            if _debug: UDPDirector._debug("    - protocol error: %r", err)
            self.handle_error(err)

    def close(self):
        if _debug: UDPDirector._debug("close")
        if self.transport:
            self.transport.close()

    def handle_error(self, error):
        if _debug: UDPDirector._debug("handle_error %r", error)
        self.close()

    def add_actor(self, actor):
        """Add an actor when a new one is connected."""
        if _debug: UDPDirector._debug("add_actor %r", actor)

        self.peers[actor.peer] = actor

        # tell the ASE there is a new client
        if self.serviceElement:
            self.sap_request(add_actor=actor)

    def del_actor(self, actor):
        """Remove an actor when the socket is closed."""
        if _debug: UDPDirector._debug("del_actor %r", actor)

        del self.peers[actor.peer]

        # tell the ASE the client has gone away
        if self.serviceElement:
            self.sap_request(del_actor=actor)

    def actor_error(self, actor, error):
        if _debug: UDPDirector._debug("actor_error %r %r", actor, error)

        # tell the ASE the actor had an error
        if self.serviceElement:
            self.sap_request(actor_error=actor, error=error)

    def get_actor(self, address):
        return self.peers.get(address, None)

    def handle_connect(self):
        if _debug: UDPDirector._debug("handle_connect")

    def readable(self):
        return 1

    def handle_read(self):
        if _debug: UDPDirector._debug("handle_read(%r)", self.address)

        try:
            msg, addr = self.socket.recvfrom(65536)
            if _debug: UDPDirector._debug("    - received %d octets from %s", len(msg), addr)

            # send the PDU up to the client
            deferred(self._response, PDU(msg, source=addr))

        except socket.timeout as err:
            if _debug: UDPDirector._debug("    - socket timeout: %s", err)

        except socket.error as err:
            if err.args[0] == 11:
                pass
            else:
                if _debug: UDPDirector._debug("    - socket error: %s", err)

                # pass along to a handler
                self.handle_error(err)

    def writable(self):
        """Return true iff there is a request pending."""
        return (not self.request.empty())

    def handle_write(self):
        """get a PDU from the queue and send it."""
        if _debug: UDPDirector._debug("handle_write(%r)", self.address)

        try:
            pdu = self.request.get()

            sent = self.socket.sendto(pdu.pduData, pdu.pduDestination)
            if _debug: UDPDirector._debug("    - sent %d octets to %s", sent, pdu.pduDestination)

        except socket.error as err:
            if _debug: UDPDirector._debug("    - socket error: %s", err)

            # get the peer
            peer = self.peers.get(pdu.pduDestination, None)
            if peer:
                # let the actor handle the error
                peer.handle_error(err)
            else:
                # let the director handle the error
                self.handle_error(err)

    def close_socket(self):
        """Close the socket."""
        if _debug: UDPDirector._debug("close_socket")

        self.socket.close()
        self.close()
        self.socket = None

    def handle_close(self):
        """Remove this from the monitor when it's closed."""
        if _debug: UDPDirector._debug("handle_close")

        self.close()
        self.socket = None

    def handle_error(self, error=None):
        if _debug: UDPDirector._debug("handle_error %r", error)

    def indication(self, pdu):
        """Client requests are queued for delivery."""
        if _debug: UDPDirector._debug("indication %r", pdu)

        # get the destination
        addr = pdu.pduDestination

        # get the peer
        peer = self.peers.get(addr, None)
        if not peer:
            peer = self.actorClass(self, addr)

        # send the message
        peer.indication(pdu)

        # send the data through the transport
        if self.transport:
            try:
                if isinstance(pdu.pduData, bytes):
                    data = pdu.pduData
                else:
                    data = str(pdu.pduData).encode()
                self.transport.sendto(data, addr)
            except Exception as err:
                if _debug: UDPDirector._debug("    - send error: %r", err)
                self.handle_error(err)
        else:
            if _debug: UDPDirector._debug("    - no transport available")

    def _response(self, pdu):
        """Incoming datagrams are routed through an actor."""
        if _debug: UDPDirector._debug("_response %r", pdu)

        # get the destination
        addr = pdu.pduSource

        # get the peer
        peer = self.peers.get(addr, None)
        if not peer:
            peer = self.actorClass(self, addr)

        # send the message
        peer.response(pdu)

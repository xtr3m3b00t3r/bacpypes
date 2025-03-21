#!/usr/bin/python

"""
TCP Communications Module
"""

import asyncio
import socket
import errno

import pickle
from time import time as _time, sleep as _sleep
from io import StringIO

from .debugging import ModuleLogger, DebugContents, bacpypes_debugging

from .core import deferred
from .task import FunctionTask, OneShotFunction
from .comm import PDU, Client, Server
from .comm import ServiceAccessPoint, ApplicationServiceElement

# some debugging
_debug = 0
_log = ModuleLogger(globals())

# globals
REBIND_SLEEP_INTERVAL = 2.0
CONNECT_TIMEOUT = 30.0

#
#   PickleActorMixIn
#

@bacpypes_debugging
class PickleActorMixIn:

    def __init__(self, *args):
        if _debug: PickleActorMixIn._debug("__init__ %r", args)
        super(PickleActorMixIn, self).__init__(*args)

        # keep an upstream buffer
        self.pickleBuffer = ''

    def indication(self, pdu):
        if _debug: PickleActorMixIn._debug("indication %r", pdu)

        # pickle the data
        pdu.pduData = pickle.dumps(pdu.pduData)

        # continue as usual
        super(PickleActorMixIn, self).indication(pdu)

    def response(self, pdu):
        if _debug: PickleActorMixIn._debug("response %r", pdu)

        # add the data to our buffer
        self.pickleBuffer += pdu.pduData

        # build a file-like object around the buffer
        strm = StringIO(self.pickleBuffer)

        pos = 0
        while (pos < strm.len):
            try:
                # try to load something
                msg = pickle.load(strm)
            except:
                break

            # got a message
            rpdu = PDU(msg)
            rpdu.update(pdu)

            super(PickleActorMixIn, self).response(rpdu)

            # see where we are
            pos = strm.tell()

        # save anything left over, if there is any
        if (pos < strm.len):
            self.pickleBuffer = self.pickleBuffer[pos:]
        else:
            self.pickleBuffer = ''

#
#   TCPClient
#
#   This class is a mapping between the client/server pattern and the
#   socket API.  The ctor is given the address to connect as a TCP
#   client.  Because objects of this class sit at the bottom of a
#   protocol stack they are accessed as servers.
#

@bacpypes_debugging
class TCPClient:
    def __init__(self, peer):
        if _debug: TCPClient._debug("__init__ %r", peer)
        
        # create the socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setblocking(False)
        
        # save the peer and connection state
        self.peer = peer
        self.connected = False
        self._closing = False
        
        # create request buffer and transport
        self.request = b''
        self.transport = None
        
        # get the event loop
        self.loop = asyncio.get_event_loop()
        
        # start connection
        self.connect()
    
    async def connect(self):
        if _debug: TCPClient._debug("connect")
        try:
            await self.loop.create_connection(
                lambda: self._protocol_factory(),
                self.peer[0],
                self.peer[1]
            )
        except Exception as err:
            if _debug: TCPClient._debug("    - connection error: %r", err)
            self.handle_error(err)
    
    def _protocol_factory(self):
        return TCPClientProtocol(self)
    
    def close(self):
        if _debug: TCPClient._debug("close")
        if self.transport:
            self.transport.close()
    
    def handle_connect(self):
        if _debug: TCPClient._debug("handle_connect")
        self.connected = True
    
    def handle_error(self, error):
        if _debug: TCPClient._debug("handle_error %r", error)
        self.close()
    
    def indication(self, pdu):
        if _debug: TCPClient._debug("indication %r", pdu)
        
        if isinstance(pdu.pduData, bytes):
            data = pdu.pduData
        else:
            data = pdu.pduData.encode()
        
        self.request = data
        if self.transport and self.connected:
            self.transport.write(self.request)
            self.request = b''

class TCPClientProtocol(asyncio.Protocol):
    def __init__(self, client):
        self.client = client
    
    def connection_made(self, transport):
        if _debug: TCPClient._debug("connection_made")
        self.client.transport = transport
        self.client.handle_connect()
    
    def data_received(self, data):
        if _debug: TCPClient._debug("data_received %r", data)
        deferred(self.client.response, PDU(data))
    
    def connection_lost(self, exc):
        if _debug: TCPClient._debug("connection_lost %r", exc)
        self.client.connected = False
        if exc:
            self.client.handle_error(exc)

    _connect_timeout = CONNECT_TIMEOUT

    def __init__(self, peer):
        if _debug: TCPClient._debug("__init__ %r", peer)
        asyncore.dispatcher.__init__(self)

        # ask the dispatcher for a socket
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)

        # make sure the connection attempt is non-blocking
        self.socket.setblocking(0)
        if _debug: TCPClient._debug("    - non-blocking")

        # save the peer
        self.peer = peer
        self.connected = False

        # create a request buffer
        self.request = b''

        # try to connect
        try:
            rslt = self.socket.connect_ex(peer)
            if (rslt == 0):
                if _debug: TCPClient._debug("    - connected")
                self.connected = True
            elif (rslt == errno.EINPROGRESS):
                if _debug: TCPClient._debug("    - in progress")
            elif (rslt == errno.ECONNREFUSED):
                if _debug: TCPClient._debug("    - connection refused")
                self.handle_error(rslt)
            else:
                if _debug: TCPClient._debug("    - connect_ex: %r", rslt)
        except socket.error as err:
            if _debug: TCPClient._debug("    - connect socket error: %r", err)

            # pass along to a handler
            self.handle_error(err)

    def handle_accept(self):
        if _debug: TCPClient._debug("handle_accept")

    def handle_connect(self):
        if _debug: TCPClient._debug("handle_connect")
        self.connected = True

    def handle_connect_event(self):
        if _debug: TCPClient._debug("handle_connect_event")

        # there might be an error
        err = self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if _debug: TCPClient._debug("    - err: %r", err)

        # check for connection refused
        if (err == 0):
            if _debug: TCPClient._debug("    - no error")
            self.connected = True
        elif (err == errno.ECONNREFUSED):
            if _debug: TCPClient._debug("    - connection to %r refused", self.peer)
            self.handle_error(socket.error(errno.ECONNREFUSED, "connection refused"))
            return

        # pass along
        asyncore.dispatcher.handle_connect_event(self)

    def readable(self):
        return self.connected

    def handle_read(self):
        if _debug: TCPClient._debug("handle_read")

        try:
            msg = self.recv(65536)
            if _debug: TCPClient._debug("    - received %d octets", len(msg))

            # no socket means it was closed
            if not self.socket:
                if _debug: TCPClient._debug("    - socket was closed")
            else:
                # send the data upstream
                deferred(self.response, PDU(msg))

        except socket.error as err:
            if (err.args[0] == errno.ECONNREFUSED):
                if _debug: TCPClient._debug("    - connection to %r refused", self.peer)
            else:
                if _debug: TCPClient._debug("    - recv socket error: %r", err)

            # pass along to a handler
            self.handle_error(err)

    def writable(self):
        if not self.connected:
            return True

        return (len(self.request) != 0)

    def handle_write(self):
        if _debug: TCPClient._debug("handle_write")

        try:
            sent = self.send(self.request)
            if _debug: TCPClient._debug("    - sent %d octets, %d remaining", sent, len(self.request) - sent)

            self.request = self.request[sent:]

        except socket.error as err:
            if (err.args[0] == errno.EPIPE):
                if _debug: TCPClient._debug("    - broken pipe to %r", self.peer)
                return
            elif (err.args[0] == errno.ECONNREFUSED):
                if _debug: TCPClient._debug("    - connection to %r refused", self.peer)
            else:
                if _debug: TCPClient._debug("    - send socket error: %s", err)

            # pass along to a handler
            self.handle_error(err)

    def handle_write_event(self):
        if _debug: TCPClient._debug("handle_write_event")

        # there might be an error
        err = self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if _debug: TCPClient._debug("    - err: %r", err)

        # check for connection refused
        if err == 0:
            if not self.connected:
                if _debug: TCPClient._debug("    - connected")
                self.handle_connect()
        else:
            if _debug: TCPClient._debug("    - peer: %r", self.peer)

            if (err == errno.ECONNREFUSED):
                socket_error = socket.error(err, "connection refused")
            elif (err == errno.ETIMEDOUT):
                socket_error = socket.error(err, "timed out")
            elif (err == errno.EHOSTUNREACH):
                socket_error = socket.error(err, "host unreachable")
            else:
                socket_error = socket.error(err, "other unknown: %r" % (err,))
            if _debug: TCPClient._debug("    - socket_error: %r", socket_error)

            self.handle_error(socket_error)
            return

        # pass along
        asyncore.dispatcher.handle_write_event(self)

    def handle_close(self):
        if _debug: TCPClient._debug("handle_close")

        # close the socket
        self.close()

        # no longer connected
        self.connected = False

        # make sure other routines know the socket is closed
        self.socket = None

    def handle_error(self, error=None):
        """Trap for TCPClient errors, otherwise continue."""
        if _debug: TCPClient._debug("handle_error %r", error)

        # if there is no socket, it was closed
        if not self.socket:
            if _debug: TCPClient._debug("    - error already handled")
            return

        # core does not take parameters
        asyncore.dispatcher.handle_error(self)

    def indication(self, pdu):
        """Requests are queued for delivery."""
        if _debug: TCPClient._debug("indication %r", pdu)

        self.request += pdu.pduData

#
#   TCPClientActor
#
#   Actors are helper objects for a director.  There is one actor for
#   each connection.
#

@bacpypes_debugging
class TCPClientActor(TCPClient):

    def __init__(self, director, peer):
        if _debug: TCPClientActor._debug("__init__ %r %r", director, peer)

        # no director yet, no connection error
        self.director = None
        self._connection_error = None

        # add a timer
        self._connect_timeout = director.connect_timeout
        if self._connect_timeout:
            self.connect_timeout_task = FunctionTask(self.connect_timeout)
            self.connect_timeout_task.install_task(_time() + self._connect_timeout)
        else:
            self.connect_timeout_task = None

        # continue with initialization
        TCPClient.__init__(self, peer)

        # keep track of the director
        self.director = director

        # add a timer
        self._idle_timeout = director.idle_timeout
        if self._idle_timeout:
            self.idle_timeout_task = FunctionTask(self.idle_timeout)
            self.idle_timeout_task.install_task(_time() + self._idle_timeout)
        else:
            self.idle_timeout_task = None

        # this may have a flush state
        self.flush_task = None

        # tell the director this is a new actor
        self.director.add_actor(self)

        # if there was a connection error, pass it to the director
        if self._connection_error:
            if _debug: TCPClientActor._debug("    - had connection error")
            self.director.actor_error(self, self._connection_error)

    def handle_connect(self):
        if _debug: TCPClientActor._debug("handle_connect")

        # see if we are already connected
        if self.connected:
            if _debug: TCPClientActor._debug("    - already connected")
            return

        # if the connection timeout is scheduled, suspend it
        if self.connect_timeout_task:
            if _debug: TCPClientActor._debug("    - canceling connection timeout")
            self.connect_timeout_task.suspend_task()
            self.connect_timeout_task = None

        # contine as expected
        TCPClient.handle_connect(self)

    def handle_error(self, error=None):
        """Trap for TCPClient errors, otherwise continue."""
        if _debug: TCPClientActor._debug("handle_error %r", error)

        # pass along to the director
        if error is not None:
            # this error may be during startup
            if not self.director:
                self._connection_error = error
            else:
                self.director.actor_error(self, error)
        else:
            TCPClient.handle_error(self)

    def handle_close(self):
        if _debug: TCPClientActor._debug("handle_close")

        # if there's a flush task, cancel it
        if self.flush_task:
            self.flush_task.suspend_task()

        # cancel the timers
        if self.connect_timeout_task:
            if _debug: TCPClientActor._debug("    - canceling connection timeout")
            self.connect_timeout_task.suspend_task()
            self.connect_timeout_task = None
        if self.idle_timeout_task:
            if _debug: TCPClientActor._debug("    - canceling idle timeout")
            self.idle_timeout_task.suspend_task()
            self.idle_timeout_task = None

        # tell the director this is gone
        self.director.del_actor(self)

        # pass the function along
        TCPClient.handle_close(self)

    def connect_timeout(self):
        if _debug: TCPClientActor._debug("connect_timeout")

        # shut it down
        self.handle_close()

    def idle_timeout(self):
        if _debug: TCPClientActor._debug("idle_timeout")

        # shut it down
        self.handle_close()

    def indication(self, pdu):
        if _debug: TCPClientActor._debug("indication %r", pdu)

        # additional downstream data is tossed while flushing
        if self.flush_task:
            if _debug: TCPServerActor._debug("    - flushing")
            return

        # reschedule the timer
        if self.idle_timeout_task:
            self.idle_timeout_task.install_task(_time() + self._idle_timeout)

        # continue as usual
        TCPClient.indication(self, pdu)

    def response(self, pdu):
        if _debug: TCPClientActor._debug("response %r", pdu)

        # put the peer address in as the source
        pdu.pduSource = self.peer

        # reschedule the timer
        if self.idle_timeout_task:
            self.idle_timeout_task.install_task(_time() + self._idle_timeout)

        # process this as a response from the director
        self.director.response(pdu)

    def flush(self):
        if _debug: TCPClientActor._debug("flush")

        # clear out the old task
        self.flush_task = None

        # if the outgoing buffer has data, re-schedule another attempt
        if self.request:
            self.flush_task = OneShotFunction(self.flush)
            return

        # close up shop, all done
        self.handle_close()

#
#   TCPPickleClientActor
#

class TCPPickleClientActor(PickleActorMixIn, TCPClientActor):
    pass

#
#   TCPClientDirector
#
#   A client director presents a connection pool as one virtual
#   interface.  If a request should be sent to an address and there
#   is no connection already established for it, it will create one
#   and maintain it.  PDU's from TCP clients have no source address,
#   so one is provided by the client actor.
#

@bacpypes_debugging
class TCPClientDirector(Server, ServiceAccessPoint, DebugContents):

    _debug_contents = ('connect_timeout', 'idle_timeout', 'actorClass', 'clients', 'reconnect')

    def __init__(self, connect_timeout=None, idle_timeout=None, actorClass=TCPClientActor, sid=None, sapID=None):
        if _debug:
            TCPClientDirector._debug("__init__ connect_timeout=%r idle_timeout=%r actorClass=%r sid=%r sapID=%r",
            connect_timeout, idle_timeout, actorClass, sid, sapID,
            )
        Server.__init__(self, sid)
        ServiceAccessPoint.__init__(self, sapID)

        # check the actor class
        if not issubclass(actorClass, TCPClientActor):
            raise TypeError("actorClass must be a subclass of TCPClientActor")
        self.actorClass = actorClass

        # save the timeout for actors
        self.connect_timeout = connect_timeout
        self.idle_timeout = idle_timeout

        # start with an empty client pool
        self.clients = {}

        # no clients automatically reconnecting
        self.reconnect = {}

    def add_actor(self, actor):
        """Add an actor when a new one is connected."""
        if _debug: TCPClientDirector._debug("add_actor %r", actor)

        self.clients[actor.peer] = actor

        # tell the ASE there is a new client
        if self.serviceElement:
            self.sap_request(add_actor=actor)

    def del_actor(self, actor):
        """Remove an actor when the socket is closed."""
        if _debug: TCPClientDirector._debug("del_actor %r", actor)

        # delete the client
        del self.clients[actor.peer]

        # tell the ASE the client has gone away
        if self.serviceElement:
            self.sap_request(del_actor=actor)

        # see if it should be reconnected
        if actor.peer in self.reconnect:
            connect_task = FunctionTask(self.connect, actor.peer)
            connect_task.install_task(_time() + self.reconnect[actor.peer])

    def actor_error(self, actor, error):
        if _debug: TCPClientDirector._debug("actor_error %r %r", actor, error)

        # tell the ASE the actor had an error
        if self.serviceElement:
            self.sap_request(actor_error=actor, error=error)

    def get_actor(self, address):
        """ Get the actor associated with an address or None. """
        return self.clients.get(address, None)

    def connect(self, address, reconnect=0):
        if _debug: TCPClientDirector._debug("connect %r reconnect=%r", address, reconnect)
        if address in self.clients:
            return

        # create an actor, which will eventually call add_actor
        client = self.actorClass(self, address)
        if _debug: TCPClientDirector._debug("    - client: %r", client)

        # if it should automatically reconnect, save the timer value
        if reconnect:
            self.reconnect[address] = reconnect

    def disconnect(self, address):
        if _debug: TCPClientDirector._debug("disconnect %r", address)
        if address not in self.clients:
            return

        # if it would normally reconnect, don't bother
        if address in self.reconnect:
            del self.reconnect[address]

        # close it
        self.clients[address].handle_close()

    def indication(self, pdu):
        """Direct this PDU to the appropriate server, create a
        connection if one hasn't already been created."""
        if _debug: TCPClientDirector._debug("indication %r", pdu)

        # get the destination
        addr = pdu.pduDestination

        # get the client
        client = self.clients.get(addr, None)
        if not client:
            client = self.actorClass(self, addr)

        # send the message
        client.indication(pdu)

#
#   TCPServer
#

@bacpypes_debugging
class TCPServer:
    def __init__(self, sock, peer):
        if _debug: TCPServer._debug("__init__ %r %r", sock, peer)
        
        # save the peer and socket
        self.peer = peer
        self.socket = sock
        self.socket.setblocking(False)
        
        # create a request buffer and transport
        self.request = b''
        self.transport = None
        
        # get the event loop
        self.loop = asyncio.get_event_loop()
        
        # create protocol
        self._protocol = TCPServerProtocol(self)
        
        # start serving
        self.loop.create_task(self.start_serving())
    
    async def start_serving(self):
        if _debug: TCPServer._debug("start_serving")
        try:
            self.transport, _ = await self.loop.create_connection(
                lambda: self._protocol,
                sock=self.socket
            )
        except Exception as err:
            if _debug: TCPServer._debug("    - server error: %r", err)
            self.handle_error(err)
    
    def close(self):
        if _debug: TCPServer._debug("close")
        if self.transport:
            self.transport.close()
    
    def handle_error(self, error):
        if _debug: TCPServer._debug("handle_error %r", error)
        self.close()
    
    def indication(self, pdu):
        if _debug: TCPServer._debug("indication %r", pdu)
        
        if isinstance(pdu.pduData, bytes):
            data = pdu.pduData
        else:
            data = str(pdu.pduData).encode()
        
        if self.transport:
            try:
                self.transport.write(data)
            except Exception as err:
                if _debug: TCPServer._debug("    - send error: %r", err)
                self.handle_error(err)
        else:
            if _debug: TCPServer._debug("    - no transport available")

class TCPServerProtocol(asyncio.Protocol):
    def __init__(self, server):
        self.server = server
    
    def connection_made(self, transport):
        if _debug: TCPServerProtocol._debug("connection_made %r", transport)
        self.server.transport = transport
    
    def data_received(self, data):
        if _debug: TCPServerProtocol._debug("data_received %r", data)
        deferred(self.server.response, PDU(data))
    
    def connection_lost(self, exc):
        if _debug: TCPServerProtocol._debug("connection_lost %r", exc)
        if exc:
            self.server.handle_error(exc)

    def __init__(self, server):
        if _debug: TCPServerProtocol._debug("__init__ %r", server)
        self.server = server

    def response(self, pdu):
        if _debug: TCPServerProtocol._debug("response %r", pdu)
        deferred(self.server.response, pdu)

    def handle_error(self, error):
        if _debug: TCPServerProtocol._debug("handle_error %r", error)
        if self.server:
            self.server.handle_error(error)

#
#   TCPServerActor
#

@bacpypes_debugging
class TCPServerActor(TCPServer):

    def __init__(self, director, sock, peer):
        if _debug: TCPServerActor._debug("__init__ %r %r %r", director, sock, peer)
        TCPServer.__init__(self, sock, peer)

        # keep track of the director
        self.director = director

        # add a timer
        self._idle_timeout = director.idle_timeout
        if self._idle_timeout:
            self.idle_timeout_task = FunctionTask(self.idle_timeout)
            self.idle_timeout_task.install_task(_time() + self._idle_timeout)
        else:
            self.idle_timeout_task = None

        # this may have a flush state
        self.flush_task = None

        # tell the director this is a new actor
        self.director.add_actor(self)

    async def start_serving(self):
        if _debug: TCPServerActor._debug("start_serving")
        try:
            self.transport, _ = await self.loop.create_connection(
                lambda: self._protocol,
                sock=self.socket
            )
        except Exception as err:
            if _debug: TCPServerActor._debug("    - server error: %r", err)
            self.handle_error(err)

    def handle_error(self, error=None):
        """Trap for TCPServer errors, otherwise continue."""
        if _debug: TCPServerActor._debug("handle_error %r", error)

        # pass it along to the director
        self.director.actor_error(self, error)

    def handle_close(self):
        if _debug: TCPServerActor._debug("handle_close")

        # if there is an idle timeout task, cancel it
        if self._idle_timeout:
            self.idle_timeout_task.suspend_task()

        # if there is a flush task, cancel it
        if self.flush_task:
            self.flush_task.suspend_task()

        # tell the director this is gone
        self.director.del_actor(self)

        # pass it down
        self.close()

    def idle_timeout(self):
        if _debug: TCPServerActor._debug("idle_timeout")

        # pass it along
        self.director.actor_idle_timeout(self)

    def indication(self, pdu):
        if _debug: TCPServerActor._debug("indication %r", pdu)

        # make sure it has a source
        if not pdu.pduSource:
            pdu.pduSource = self.director.port

        # send it downstream
        super(TCPServerActor, self).indication(pdu)

    def response(self, pdu):
        if _debug: TCPServerActor._debug("response %r", pdu)

        # make sure it has a destination
        if not pdu.pduDestination:
            pdu.pduDestination = self.peer

        # send it upstream
        self.director.response(pdu)

    def flush(self):
        if _debug: TCPServerActor._debug("flush")

        # pass it along
        self.director.actor_flush(self)





        # if there is an idle timeout, cancel it
        if self.idle_timeout_task:
            if _debug: TCPServerActor._debug("    - canceling idle timeout")
            self.idle_timeout_task.suspend_task()
            self.idle_timeout_task = None

        # tell the director this is gone
        self.director.del_actor(self)

        # pass it down
        TCPServer.handle_close(self)

    def idle_timeout(self):
        if _debug: TCPServerActor._debug("idle_timeout")

        # shut it down
        self.handle_close()

    def indication(self, pdu):
        if _debug: TCPServerActor._debug("indication %r", pdu)

        # additional downstream data is tossed while flushing
        if self.flush_task:
            if _debug: TCPServerActor._debug("    - flushing")
            return

        # reschedule the timer
        if self.idle_timeout_task:
            self.idle_timeout_task.install_task(_time() + self._idle_timeout)

        # continue as usual
        TCPServer.indication(self, pdu)

    def response(self, pdu):
        if _debug: TCPServerActor._debug("response %r", pdu)

        # upstream data is tossed while flushing
        if self.flush_task:
            if _debug: TCPServerActor._debug("    - flushing")
            return

        # save the source
        pdu.pduSource = self.peer

        # reschedule the timer
        if self.idle_timeout_task:
            self.idle_timeout_task.install_task(_time() + self._idle_timeout)

        # process this as a response from the director
        self.director.response(pdu)

    def flush(self):
        if _debug: TCPServerActor._debug("flush")

        # clear out the old task
        self.flush_task = None

        # if the outgoing buffer has data, re-schedule another attempt
        if self.request:
            self.flush_task = OneShotFunction(self.flush)
            return

        # close up shop, all done
        self.handle_close()

#
#   TCPPickleServerActor
#

class TCPPickleServerActor(PickleActorMixIn, TCPServerActor):
    pass

#
#   TCPServerDirector
#

@bacpypes_debugging
class TCPServerDirector(Server, ServiceAccessPoint, DebugContents):

    _debug_contents = ('port', 'idle_timeout', 'actorClass', 'servers')

    def __init__(self, address, listeners=5, idle_timeout=0, reuse=False, actorClass=TCPServerActor, cid=None, sapID=None):
        if _debug:
            TCPServerDirector._debug("__init__ %r listeners=%r idle_timeout=%r reuse=%r actorClass=%r cid=%r sapID=%r"
                , address, listeners, idle_timeout, reuse, actorClass, cid, sapID
                )
        Server.__init__(self, cid)
        ServiceAccessPoint.__init__(self, sapID)

        # save the address and timeout
        self.port = address
        self.idle_timeout = idle_timeout

        # check the actor class
        if not issubclass(actorClass, TCPServerActor):
            raise TypeError("actorClass must be a subclass of TCPServerActor")
        self.actorClass = actorClass

        # start with an empty pool of servers
        self.servers = {}

        # create the socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setblocking(False)
        if reuse:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # try to bind, keep trying for a while if its already in use
        hadBindErrors = False
        for i in range(30):
            try:
                self.socket.bind(address)
                break
            except socket.error as err:
                hadBindErrors = True
                TCPServerDirector._warning('bind error %r, sleep and try again', err)
                _sleep(REBIND_SLEEP_INTERVAL)
        else:
            TCPServerDirector._error('unable to bind')
            raise RuntimeError("unable to bind")

        # if there were some bind errors, generate a message that all is OK now
        if hadBindErrors:
            TCPServerDirector._info('bind successful')

        # listen for connections
        self.socket.listen(listeners)

        # get the event loop and start serving
        self.loop = asyncio.get_event_loop()
        self.loop.create_task(self.start_serving())

    async def start_serving(self):
        if _debug: TCPServerDirector._debug("start_serving")
        try:
            while True:
                client_socket, client_addr = await self.loop.sock_accept(self.socket)
                if _debug: TCPServerDirector._debug("    - connection from %r", client_addr)

                # create an actor for this connection
                actor = self.actorClass(self, client_socket, client_addr)
                self.add_actor(actor)

        except Exception as err:
            if _debug: TCPServerDirector._debug("    - server error: %r", err)
            self.handle_error(err)

    def close(self):
        if _debug: TCPServerDirector._debug("close")
        self.socket.close()

    def handle_error(self, error):
        if _debug: TCPServerDirector._debug("handle_error %r", error)
        self.close()

    def handle_accept(self):
        if _debug: TCPServerDirector._debug("handle_accept")

        try:
            client, addr = self.accept()
        except socket.error:
            TCPServerDirector._warning('accept() threw an exception')
            return
        except TypeError:
            TCPServerDirector._warning('accept() threw EWOULDBLOCK')
            return
        if _debug: TCPServerDirector._debug("    - connection %r, %r", client, addr)

        # create a server
        server = self.actorClass(self, client, addr)

        # add it to our pool
        self.servers[addr] = server

        # return it to the dispatcher
        return server

    def handle_close(self):
        if _debug: TCPServerDirector._debug("handle_close")

        # close the socket
        self.close()

    def add_actor(self, actor):
        if _debug: TCPServerDirector._debug("add_actor %r", actor)

        self.servers[actor.peer] = actor

        # tell the ASE there is a new server
        if self.serviceElement:
            self.sap_request(add_actor=actor)

    def del_actor(self, actor):
        if _debug: TCPServerDirector._debug("del_actor %r", actor)

        try:
            del self.servers[actor.peer]
        except KeyError:
            TCPServerDirector._warning("del_actor: %r not an actor", actor)

        # tell the ASE the server has gone away
        if self.serviceElement:
            self.sap_request(del_actor=actor)

    def actor_error(self, actor, error):
        if _debug: TCPServerDirector._debug("actor_error %r %r", actor, error)

        # tell the ASE the actor had an error
        if self.serviceElement:
            self.sap_request(actor_error=actor, error=error)

    def get_actor(self, address):
        """ Get the actor associated with an address or None. """
        return self.servers.get(address, None)

    def indication(self, pdu):
        """Direct this PDU to the appropriate server."""
        if _debug: TCPServerDirector._debug("indication %r", pdu)

        # get the destination
        addr = pdu.pduDestination

        # get the server
        server = self.servers.get(addr, None)
        if not server:
            raise RuntimeError("not a connected server")

        # pass the indication to the actor
        server.indication(pdu)

#
#   StreamToPacket
#

@bacpypes_debugging
class StreamToPacket(Client, Server):

    def __init__(self, fn, cid=None, sid=None):
        if _debug: StreamToPacket._debug("__init__ %r cid=%r, sid=%r", fn, cid, sid)
        Client.__init__(self, cid)
        Server.__init__(self, sid)

        # save the packet function
        self.packetFn = fn

        # start with an empty set of buffers
        self.upstreamBuffer = {}
        self.downstreamBuffer = {}

    def packetize(self, pdu, streamBuffer):
        if _debug: StreamToPacket._debug("packetize %r ...", pdu)

        def chop(addr):
            if _debug: StreamToPacket._debug("chop %r", addr)

            # get the current downstream buffer
            buff = streamBuffer.get(addr, b'') + pdu.pduData
            if _debug: StreamToPacket._debug("    - buff: %r", buff)

            # look for a packet
            while 1:
                packet = self.packetFn(buff)
                if _debug: StreamToPacket._debug("    - packet: %r", packet)
                if packet is None:
                    break

                yield PDU(packet[0],
                    source=pdu.pduSource,
                    destination=pdu.pduDestination,
                    user_data=pdu.pduUserData,
                    )
                buff = packet[1]

            # save what didn't get sent
            streamBuffer[addr] = buff

        # buffer related to the addresses
        if pdu.pduSource:
            for pdu in chop(pdu.pduSource):
                yield pdu
        if pdu.pduDestination:
            for pdu in chop(pdu.pduDestination):
                yield pdu

    def indication(self, pdu):
        """Message going downstream."""
        if _debug: StreamToPacket._debug("indication %r", pdu)

        # hack it up into chunks
        for packet in self.packetize(pdu, self.downstreamBuffer):
            self.request(packet)

    def confirmation(self, pdu):
        """Message going upstream."""
        if _debug: StreamToPacket._debug("StreamToPacket.confirmation %r", pdu)

        # hack it up into chunks
        for packet in self.packetize(pdu, self.upstreamBuffer):
            self.response(packet)

#
#   StreamToPacketSAP
#

@bacpypes_debugging
class StreamToPacketSAP(ApplicationServiceElement, ServiceAccessPoint):

    def __init__(self, stp, aseID=None, sapID=None):
        if _debug: StreamToPacketSAP._debug("__init__ %r aseID=%r, sapID=%r", stp, aseID, sapID)
        ApplicationServiceElement.__init__(self, aseID)
        ServiceAccessPoint.__init__(self, sapID)

        # save a reference to the StreamToPacket object
        self.stp = stp

    def indication(self, add_actor=None, del_actor=None, actor_error=None, error=None):
        if _debug: StreamToPacketSAP._debug("indication add_actor=%r del_actor=%r", add_actor, del_actor)

        if add_actor:
            # create empty buffers associated with the peer
            self.stp.upstreamBuffer[add_actor.peer] = b''
            self.stp.downstreamBuffer[add_actor.peer] = b''

        if del_actor:
            # delete the buffer contents associated with the peer
            del self.stp.upstreamBuffer[del_actor.peer]
            del self.stp.downstreamBuffer[del_actor.peer]

        # chain this along
        if self.serviceElement:
            self.sap_request(
                add_actor=add_actor,
                del_actor=del_actor,
                actor_error=actor_error, error=error,
                )

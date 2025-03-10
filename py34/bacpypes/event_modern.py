#!/usr/bin/python

"""
Event - Modern implementation using asyncio
"""

import asyncio
import os
import select
from .debugging import Logging, bacpypes_debugging, ModuleLogger

# some debugging
_debug = 0
_log = ModuleLogger(globals())

@bacpypes_debugging
class WaitableEvent(Logging):
    def __init__(self):
        if _debug: WaitableEvent._debug("__init__")
        self._read_fd, self._write_fd = os.pipe()
        self._loop = asyncio.get_event_loop()
        self._event = asyncio.Event()
        
        # Add the pipe reader to the event loop
        self._loop.add_reader(self._read_fd, self._handle_read)

    def __del__(self):
        if _debug: WaitableEvent._debug("__del__")
        self._loop.remove_reader(self._read_fd)
        os.close(self._read_fd)
        os.close(self._write_fd)

    def _handle_read(self):
        if _debug: WaitableEvent._debug("_handle_read")
        # Clear the pipe
        os.read(self._read_fd, 1)
        self._event.set()

    async def wait(self, timeout=None):
        if timeout is not None:
            try:
                await asyncio.wait_for(self._event.wait(), timeout)
                return True
            except asyncio.TimeoutError:
                return False
        else:
            await self._event.wait()
            return True

    def wait_sync(self, timeout=None):
        """Synchronous version of wait for compatibility"""
        rfds, _, _ = select.select([self._read_fd], [], [], timeout)
        return self._read_fd in rfds

    def isSet(self):
        return self.wait_sync(0)

    def set(self):
        if _debug: WaitableEvent._debug("set")
        if not self.isSet():
            os.write(self._write_fd, b'1')
            self._event.set()

    def clear(self):
        if _debug: WaitableEvent._debug("clear")
        if self.isSet():
            os.read(self._read_fd, 1)
            self._event.clear()

# BACpypes - Python 3.13 Compatible Fork

This is a modified version of BACpypes that has been updated for compatibility with Python 3.13. The main changes focus on replacing the deprecated `asyncore` module with modern `asyncio` functionality.

## Major Changes

1. **Asyncio Migration**: Replaced all `asyncore` based networking code with `asyncio` implementations:
   - Updated `event.py` to use asyncio event handling
   - Modified `core.py` to use asyncio's event loop
   - Rewrote `tcp.py` to use asyncio-based TCP communications
   - Updated `udp.py` to implement UDP communications with asyncio

2. **New Features**:
   - Added `cylon_info.py` script for querying Cylon BACnet controllers
   - Enhanced error handling and timeout management
   - Improved logging and debugging capabilities

3. **Dependencies**:
   - Requires Python 3.13+
   - See `requirements.txt` for complete list of dependencies

## Installation

1. Clone this repository
2. Install dependencies: `pip install -r requirements.txt`
3. Install in development mode: `pip install -e .`

## Usage

### Querying Cylon Controllers

Use the `cylon_info.py` script to query information from Cylon BACnet controllers:

```bash
python cylon_info.py --device-address 192.168.1.160
```

This will retrieve:
- Serial numbers
- Firmware versions
- FLX module information
- Additional diagnostic data

## Original Project

This is a fork of the original BACpypes project:

[![Join the chat at https://gitter.im/JoelBender/bacpypes](https://badges.gitter.im/Join%20Chat.svg)](https://gitter.im/JoelBender/bacpypes?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)

[![Documentation Status](https://readthedocs.org/projects/bacpypes/badge/?version=latest)](http://bacpypes.readthedocs.io/en/latest/?badge=latest)
  